import {
  Chessboard, INPUT_EVENT_TYPE, COLOR, BORDER_TYPE,
} from "../vendor/cm-chessboard/Chessboard.js";
import {
  PromotionDialog,
  PROMOTION_DIALOG_RESULT_TYPE,
} from "../vendor/cm-chessboard/extensions/promotion-dialog/PromotionDialog.js";
import { MOVE_CANCELED_REASON } from "../vendor/cm-chessboard/view/VisualMoveInput.js";
import { api, ApiError, DOWNLOAD_RETRY_CAP, DOWNLOAD_RETRY_MS } from "./api.js";
import { encodeState, decodeState } from "./lib/state.js";
import { toPgn } from "./lib/export.js";
import { EMPTY_PLACEMENT, splitFen, composeFen, withSideToMove, withPlacement, kingProblem } from "./lib/fen.js";
import { themeSummary } from "./lib/themes.js";
import { groupMoves, moveBadge, moveClass, COUNT_SAT } from "./lib/moves.js";
import { renderTableLine } from "./stats-view.js";
import { showPanel, whenPanelShown } from "./panels.js";
import { squareFromTarget, exceedsDragThreshold } from "./lib/board-edit.js";

const START = "8/7k/5K2/8/8/8/8/6Q1 b - - 0 1";
const SPRITE = "/vendor/cm-chessboard/assets/pieces/standard.svg";
const TRAY = {
  b: ["bk", "bq", "br", "bb", "bn", "bp"],
  w: ["wk", "wq", "wr", "wb", "wn", "wp"],
};

let board = null;
let current = START;
let lastMoves = [];      // the move list from the last /v1/moves call, for drag input
const history = [];

// Whether the explorer's first render() has happened. Its initial probe is
// deferred to the panel's first activation (see initExplorer's tail), so
// until then there is no position on screen to keep in sync with the hash.
let started = false;

// Monotonic token guarding render(): every call captures its own seq at
// entry, and bails out after each await if a newer render() has since
// started -- otherwise a slow, older in-flight render (e.g. a stale 202
// retry) could clobber the move list, summary and lastMoves of whatever
// position the user has since navigated to. lastMoves is what drag input
// trusts, so a stale overwrite there would let the user "play" a move that
// no longer applies to the position on the board.
let renderSeq = 0;

// The material whose statistics the band is showing, and the payloads we have
// already fetched. Walking a game keeps the same material until a capture or
// a promotion, so this is a cache with a very high hit rate, not an
// optimisation for its own sake.
let bandMaterial = null;
const statsCache = new Map();

async function showTableStats(material) {
  const band = document.getElementById("table-stats");
  const body = document.getElementById("table-stats-body");
  // Retire the band, but only if it is still OUR band: a failure path that
  // fires after the user has moved on belongs to a material nobody is
  // looking at any more, and hiding the band then would blank the CURRENT
  // material's context with nothing to restore it. Same guard the success
  // path below applies before it renders.
  const retire = () => {
    if (bandMaterial !== material) return;
    band.hidden = true;
    bandMaterial = null;
  };
  if (!material) { band.hidden = true; bandMaterial = null; return; }
  if (material === bandMaterial) return;
  bandMaterial = material;
  band.hidden = false;
  band.dataset.material = material;

  if (!statsCache.has(material)) {
    // materials.js's showStats() sets the same precedent: write a placeholder
    // before the await, not after. Without this the PREVIOUS material's
    // rendered chart -- headed by the previous material's name -- stays on
    // screen for the entire fetch, under a band whose dataset.material has
    // already flipped to the new one.
    body.textContent = "";
    const loading = document.createElement("p");
    loading.className = "empty";
    loading.textContent = `Loading ${material}…`;
    body.appendChild(loading);
    try {
      const res = await api.stats(material);
      // A 202 means the table is still downloading. The band is context, not
      // an answer; it stays quiet rather than starting a second poll loop
      // beside the one render() is already running for this position.
      if (res.status !== 200) { retire(); return; }
      statsCache.set(material, res.body);
    } catch {
      retire(); return;                                  // never break the board on context
    }
  }
  if (bandMaterial !== material) return;                 // superseded while awaiting
  renderTableLine(body, statsCache.get(material));
}

// initMaterials() populates #material-list asynchronously and signals
// completion by setting window.__materialsReady = true -- the same flag
// three existing UI tests already poll for this purpose. #btn-open-material
// can be clicked before that fetch resolves (a slow /v1/materials on the
// real 295-table corpus, or simply a click during first paint), and the
// list it queries would still be empty; wait for the existing signal rather
// than querying too early and silently selecting nothing.
function whenMaterialsReady() {
  if (window.__materialsReady === true) return Promise.resolve();
  return new Promise((resolve) => {
    const id = setInterval(() => {
      if (window.__materialsReady === true) { clearInterval(id); resolve(); }
    }, 20);
  });
}

function showError(err) {
  const el = document.getElementById("error-banner");
  el.hidden = false;
  el.classList.toggle("info", false);
  el.textContent = err.hint ? `${err.message} — ${err.hint}` : err.message;
}
function showInfo(text) {
  const el = document.getElementById("error-banner");
  el.hidden = false; el.classList.add("info"); el.textContent = text;
}
function clearBanner() {
  const el = document.getElementById("error-banner");
  el.hidden = true; el.textContent = ""; el.classList.remove("info");
}

// Reflect a FEN in the controls without touching the API. Used by render()
// itself: this runs before the /v1/moves call below (and before the
// kingProblem short-circuit), so the FEN field and the "to move" selector
// always show what the user just built, even on a position the probe
// below is about to reject.
function syncControls(fen) {
  document.getElementById("fen-input").value = fen;
  document.getElementById("stm-select").value = splitFen(fen).stm;
}

// A single move row, used both for the optimal group's own <ul> and for a
// band's <ul class="chips"> -- same element, same click behaviour, so a chip
// IS a row rather than a lookalike of one.
function renderMoveRow(m) {
  const li = document.createElement("li");
  li.className = moveClass(m);
  li.dataset.san = m.san;
  const san = document.createElement("span");
  san.className = "san";
  san.textContent = m.san;
  li.appendChild(san);
  const text = moveBadge(m);
  if (text) {
    const badge = document.createElement("span");
    badge.className = "badge";
    badge.textContent = text;
    li.appendChild(badge);
  }
  // Every row is clickable, including the dead ones: walking into a
  // position with no helpmate is a legitimate thing to want to look at,
  // and that is the behaviour the list has today.
  li.addEventListener("click", () => { history.push(current); render(m.fen); });
  return li;
}

// A group with `bands` (Slower, No mate) renders one shared distance label
// per band plus its moves as chips -- the distance is a fact of the band,
// not of any one move, so stating it once removes the per-row repetition
// that made the Slower group 25 rows of near-identical text. A group
// without `bands` (Optimal) keeps full rows: its per-move solution count
// differs move to move, which is exactly what the list exists to show.
function renderGroup(sec, g) {
  if (!g.bands) {
    const ul = document.createElement("ul");
    for (const m of g.moves) ul.appendChild(renderMoveRow(m));
    sec.appendChild(ul);
    return;
  }
  for (const band of g.bands) {
    const wrap = document.createElement("div");
    wrap.className = "band";
    // The label cell is ALWAYS emitted, even empty (the no-mate group's
    // band() returns null): .band is a two-column grid, and skipping the
    // cell for a null label would leave the <ul class="chips"> as the
    // grid's first child instead of its second -- landing it in the label
    // column (3.2rem) rather than the chip column (1fr), which wraps every
    // chip onto its own row. An empty span with no text content renders no
    // visible character and no gap artefact; it is exactly as tall as the
    // chips beside it, so nothing shifts.
    const lab = document.createElement("span");
    lab.className = "band-label";
    if (band.label) lab.textContent = band.label;
    wrap.appendChild(lab);
    const ul = document.createElement("ul");
    ul.className = "chips";
    for (const m of band.moves) ul.appendChild(renderMoveRow(m));
    wrap.appendChild(ul);
    sec.appendChild(wrap);
  }
}

// #move-list is a <div> of <section class="move-group">, not a <ul>. Seven UI
// tests use `#move-list li` as their "the page is ready" idiom and two COUNT
// it, so a group header must never be an <li> -- it is the section's <h3>,
// outside the <ul>. A banded group nests its rows one level deeper still
// (section > .band > ul.chips > li rather than section > ul > li), but
// `#move-list li` is a descendant selector and does not care about depth, so
// it keeps selecting exactly the move rows either way.
function renderMoveList(el, moves) {
  el.textContent = "";
  const groups = groupMoves(moves);
  if (!groups.length) {
    // A mated or stalemated position has no legal moves. Say so as prose: an
    // <li> here would be counted as a move by every selector above.
    const p = document.createElement("p");
    p.className = "empty";
    p.textContent = "no legal moves — this position is mate or stalemate";
    el.appendChild(p);
    return;
  }
  for (const g of groups) {
    const sec = document.createElement("section");
    sec.className = "move-group";
    sec.dataset.group = g.key;

    const h = document.createElement("h3");
    h.className = "eyebrow";
    h.append(g.label, " ");
    const n = document.createElement("span");
    n.className = "n";
    n.textContent = g.moves.length;
    h.appendChild(n);
    sec.appendChild(h);

    renderGroup(sec, g);
    el.appendChild(sec);
  }
}

async function render(fen, { push = true, retries = 0 } = {}) {
  const seq = ++renderSeq;
  current = fen;
  syncControls(fen);
  // Reference material is for a newcomer meeting the landing position; once
  // the user has a position of their own it gets out of the way. The
  // benchmark does the same with its About/Download copy, and the reasoning
  // is the same: a published tool explains itself, then stops talking.
  const landing = fen === START;
  document.getElementById("explorer-help").hidden = !landing;
  document.getElementById("primer").hidden = !landing;
  // A hand-typed FEN may be malformed (wrong rank count, stray characters).
  // cm-chessboard's own FEN parser rejects that -- setPosition is `async`, so
  // the rejection surfaces on the returned promise, not as a synchronous
  // throw -- which would otherwise crash render() (and leave an unhandled
  // rejection) before the request below ever runs and the server gets a
  // chance to reject it with a proper ApiError + hint. Swallow it here and
  // let the /v1/moves call below drive the error banner instead.
  try {
    const p = board.setPosition(fen.split(" ")[0], true);
    if (p && typeof p.catch === "function") p.catch(() => { /* invalid FEN, handled below via ApiError */ });
  } catch { /* invalid FEN, handled below via ApiError */ }
  document.getElementById("btn-back").disabled = history.length === 0;
  // Preserve whatever panel is currently active (e.g. a deep link like
  // #panel=materials) -- hardcoding "explorer" here would clobber it the
  // moment the initial render pushes its own hash entry.
  if (push) location.hash = encodeState({ fen, panel: decodeState(location.hash).panel });

  const summary = document.getElementById("position-summary");
  const moveList = document.getElementById("move-list");
  const linesEl = document.getElementById("lines");
  const themesEl = document.getElementById("position-themes");

  // A position with a missing or duplicated king is one the editor produces
  // on the way to a real position; say so plainly instead of spending a round
  // trip to be told "invalid FEN".
  const kings = kingProblem(splitFen(fen).placement);
  if (kings) {
    summary.textContent = kings;
    summary.classList.add("muted");
    clearBanner();
    lastMoves = [];
    // No replacement is coming for this position: clear explicitly rather
    // than leaving a previous position's moves, lines or themes on screen
    // under it.
    moveList.textContent = "";
    linesEl.textContent = "";
    linesEl.dataset.lines = "[]";
    themesEl.textContent = "";
    showTableStats(null);
    return;
  }

  let res;
  try {
    res = await api.moves(fen);
  } catch (err) {
    if (seq !== renderSeq) return;   // superseded by a newer render()
    if (err instanceof ApiError) {
      showError(err);
      summary.textContent = "";
      // The board must never match a drag against a move list belonging to a
      // position that is no longer on screen: doing so navigates to that
      // move's child, silently discarding whatever the user just built.
      lastMoves = [];
      // Same as kingProblem above: no replacement is coming, and leaving a
      // previous position's moves on screen under a red banner would be
      // worse than an empty list.
      moveList.textContent = "";
      linesEl.textContent = "";
      linesEl.dataset.lines = "[]";
      themesEl.textContent = "";
      return;
    }
    throw err;
  }
  if (seq !== renderSeq) return;     // superseded by a newer render()

  if (res.status === 202) {
    // Neither exit below has a replacement to swap in for this position --
    // board.setPosition() and syncControls() above have already moved the
    // board and the FEN field here, so leaving the PREVIOUS position's
    // lastMoves/move list/lines/themes on screen would let a click on a
    // now-stale row navigate to a child of a position no longer displayed,
    // exactly the H1 failure fixed above -- reachable here on nothing more
    // than a routine "downloading…" banner, not a coincidental uci match.
    lastMoves = [];
    moveList.textContent = "";
    linesEl.textContent = "";
    linesEl.dataset.lines = "[]";
    themesEl.textContent = "";
    if (retries >= DOWNLOAD_RETRY_CAP) {
      showError({
        message: "Still downloading",
        hint: "this is taking longer than expected -- reloading the page will resume the download",
      });
      return;
    }
    showInfo(`downloading ${res.body.material}…`);
    setTimeout(() => {
      if (seq !== renderSeq) return; // user navigated away: stop retrying
      render(fen, { push: false, retries: retries + 1 });
    }, DOWNLOAD_RETRY_MS);
    return;
  }
  clearBanner();

  const b = res.body;
  lastMoves = b.moves;
  showTableStats(b.material);
  summary.classList.toggle("muted", b.solvable === false);
  // b.count is min(255, sum of the optimal children's counts), so the moment
  // any child badge below reads "255+ ways" this position's own count is
  // guaranteed to have saturated too -- a bare "255 optimal line(s)" here
  // would present that ceiling as a measurement, inches above badges that
  // correctly say otherwise. COUNT_SAT is the one source of truth for the
  // ceiling; no second 255 literal.
  const lines = b.count >= COUNT_SAT
    ? `${COUNT_SAT}+ optimal lines`
    : `${b.count} optimal line(s)`;
  summary.textContent = b.solvable === false
    ? "no helpmate from this position"
    : `dtm ${b.dtm} (${b.notation}) · ${lines}` +
      (b.flipped ? " · colors flipped" : "");

  if (b.solvable !== false) {
    // A second call, like the /v1/line one below: themes are opt-in on
    // /v1/probe precisely so the moves request stays cheap. A colour-flipped
    // probe answers with themes: null plus a themes_note explaining why
    // detection didn't run -- show that note rather than leaving the line
    // blank or misreporting it as "no themes detected".
    api.probe(fen, true).then(({ body }) => {
      if (seq !== renderSeq) return;         // superseded by a newer render()
      themesEl.textContent = body.themes_note || themeSummary(body.themes);
    }).catch(() => {
      if (seq !== renderSeq) return;         // superseded by a newer render()
      // Found while enumerating render()'s exits for the 202 fix above: a
      // failed probe used to leave whatever the PREVIOUS position's themes
      // were on screen, under this position's own (correct) summary --
      // never a navigation bug like H1, since lastMoves/moveList are
      // already this position's, but still exactly the staleness "replace,
      // never clear-then-fill" exists to rule out. No replacement is
      // coming for this position's themes; annotation is a nicety, but a
      // wrong one is worse than an absent one.
      themesEl.textContent = "";
    });
  } else {
    // No probe call is coming for an unsolvable position: nothing will ever
    // overwrite a previous position's themes note otherwise.
    themesEl.textContent = "";
  }

  // Replace, never clear-then-fill. Emptying these before the await made
  // everything below the list jump up ~286px for the duration of the fetch.
  // The old code also cleared the move list, lines and themes but NOT the
  // summary, which is why two tests were able to pass while reading the
  // previous position's verdict.
  const next = document.createElement("div");
  renderMoveList(next, b.moves);
  moveList.replaceChildren(...next.childNodes);

  if (b.solvable !== false) {
    try {
      const ls = await api.line(fen, true);
      if (seq !== renderSeq) return; // superseded by a newer render()
      const nextLines = document.createElement("div");
      for (const line of ls.body.lines) {
        const li = document.createElement("li");
        li.textContent = line.join(" ");
        nextLines.appendChild(li);
      }
      linesEl.replaceChildren(...nextLines.childNodes);
      linesEl.dataset.lines = JSON.stringify(ls.body.lines);
    } catch (err) {
      if (seq !== renderSeq) return; // superseded by a newer render()
      if (!(err instanceof ApiError)) throw err;
      // Same finding as the /v1/probe catch above, for /v1/line: a
      // partial-table-set 404 here (real -- app.py's /v1/line can 404 a
      // solvable position whose optimal line runs through material this
      // install hasn't generated) used to leave a previous position's
      // lines on screen with no replacement ever coming.
      linesEl.textContent = "";
      linesEl.dataset.lines = "[]";
    }
  } else {
    // Same as themesEl above: no /v1/line call is coming.
    linesEl.textContent = "";
    linesEl.dataset.lines = "[]";
  }
}

// ---- position editor -------------------------------------------------

// Dragging a piece out of the palette and onto a square. cm-chessboard has no
// notion of an external drag source, so this is ours: capture the pointer,
// carry a ghost, and ask the document what is under the pointer on release.
// The board's own data-square attributes do the hit testing, so orientation
// and the coordinate frame need no arithmetic here.
function enablePaletteDrag(btn, piece) {
  btn.addEventListener("pointerdown", (down) => {
    if (down.button !== 0) return;
    const from = { x: down.clientX, y: down.clientY };
    let ghost = null;

    const move = (e) => {
      if (!ghost) {
        if (!exceedsDragThreshold(from, { x: e.clientX, y: e.clientY })) return;
        ghost = btn.cloneNode(true);
        ghost.className = "drag-ghost";
        ghost.removeAttribute("id");
        document.body.appendChild(ghost);
      }
      ghost.style.left = `${e.clientX - 20}px`;
      ghost.style.top = `${e.clientY - 20}px`;
    };

    const up = (e) => {
      btn.removeEventListener("pointermove", move);
      btn.removeEventListener("pointerup", up);
      btn.removeEventListener("pointercancel", up);
      if (!ghost) return;                       // it was a click; let click handle it
      ghost.remove();
      ghost = null;
      // A pointercancel is not a completed drag -- nothing was dropped, and
      // per spec a cancel never produces a click, so there is no click to
      // suppress. Setting the flag anyway would leave it stuck forever
      // (only a click clears it), silently swallowing the user's next tap
      // on this button. A cancel can happen for reasons that have nothing
      // to do with us (e.g. the browser reclaiming the gesture for a page
      // scroll), so this path has to stay inert rather than guess at where
      // the pointer ended up.
      if (e.type === "pointercancel") return;
      const square = squareFromTarget(document.elementFromPoint(e.clientX, e.clientY));
      if (!square) return;                      // dropped off the board: no-op
      board.setPiece(square, piece).then(commitPlacement);
    };

    btn.setPointerCapture(down.pointerId);
    btn.addEventListener("pointermove", move);
    btn.addEventListener("pointerup", up);
    btn.addEventListener("pointercancel", up);
  });
}

function buildPalette() {
  for (const color of Object.keys(TRAY)) {
    const box = document.querySelector(`.tray[data-color="${color}"]`);
    for (const piece of TRAY[color]) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.dataset.piece = piece;
      btn.title = piece;
      btn.setAttribute("aria-label", piece);
      const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
      svg.setAttribute("viewBox", "0 0 40 40");
      const use = document.createElementNS("http://www.w3.org/2000/svg", "use");
      use.setAttribute("href", `${SPRITE}#${piece}`);
      svg.appendChild(use);
      btn.appendChild(svg);
      enablePaletteDrag(btn, piece);
      box.appendChild(btn);
    }
  }
  document.getElementById("btn-clear-board").addEventListener("click", () => {
    board.setPosition(EMPTY_PLACEMENT, false).then(() => {
      const fen = composeFen(EMPTY_PLACEMENT, splitFen(current).stm);
      history.push(current);
      render(fen);
    });
  });
}

// ---- board input -----------------------------------------------------

// One rule, no modes. A drag whose from/to matches a legal move plays it; any
// other drag relocates the piece; a drag off the board deletes it. Editing is
// never gated behind a control, which is what lets three buttons and the whole
// armed-state machinery go.
//
// `playedMove` guards exactly one path: the multi-candidate promotion branch
// below, where several underpromotion moves share one uci prefix and the
// actual choice is deferred to the vendored dialog. The real event order
// (read from vendor/cm-chessboard/view/VisualMoveInput.js): validateMoveInput
// runs synchronously inside validateMoveInputCallback (:61-65), which then
// resolves moveInputProcess; moveInputFinished fires one MICROTASK later, via
// the `.then()` registered at :47-52 -- it does not wait for the drop's
// visual animation. board.getPosition() reads state.position.getFen(), a
// plain data model that Chessboard.js's movePiece/setPosition update
// synchronously, never the DOM.
//
// On the plain-move and single-candidate paths that timing is harmless: our
// own render() call already ran synchronously inside validateMoveInput (it
// sets `current` and calls board.setPosition() before its first await), so
// by the time moveInputFinished's commitPlacement() runs a microtask later,
// board.getPosition() already agrees with `current` -- and commitPlacement's
// own `fen === current` check would no-op regardless. The promotion branch
// is different: showPromotionDialog() only calls render() once the user
// picks a piece, so nothing has touched `current` yet when moveInputFinished
// fires -- but cm-chessboard's own movePiece() has already moved the PAWN
// (not yet a queen) onto the promotion square. Without this flag,
// commitPlacement() would commit that mismatch as a bogus relocation -- an
// unpromoted pawn on the back rank -- before the dialog's own render() ever
// gets a chance to land the real, chosen move.
let playedMove = false;

function commitPlacement() {
  const fen = withPlacement(current, board.getPosition());
  if (fen === current) return;        // nothing actually moved
  history.push(current);
  render(fen);
}

function enableBoardInput() {
  board.enableMoveInput((event) => {
    if (event.type === INPUT_EVENT_TYPE.moveInputCanceled) {
      if (event.reason === MOVE_CANCELED_REASON.movedOutOfBoard)
        board.setPiece(event.squareFrom, null).then(commitPlacement);
      return;
    }
    if (event.type === INPUT_EVENT_TYPE.moveInputFinished) {
      if (playedMove) { playedMove = false; return; }
      commitPlacement();
      return;
    }
    if (event.type !== INPUT_EVENT_TYPE.validateMoveInput) return true;

    const uci = `${event.squareFrom}${event.squareTo}`;
    const moves = lastMoves || [];

    const exact = moves.find((m) => m.uci === uci);
    if (exact) {
      playedMove = true;
      history.push(current);
      render(exact.fen);
      return true;
    }

    const candidates = moves.filter(
      (m) => m.uci.length === uci.length + 1 && m.uci.startsWith(uci)
    );
    // Not a legal move: accept the drag anyway and let moveInputFinished
    // commit it as a relocation. Returning false here would snap the piece
    // back, which is the old play-only behaviour.
    if (candidates.length === 0) return true;

    if (candidates.length === 1) {
      playedMove = true;
      history.push(current);
      render(candidates[0].fen);
      return true;
    }

    // Several underpromotion choices are legal: ask the user which piece.
    playedMove = true;
    const fromFen = current;
    const color = event.piece.charAt(0); // "wp" -> "w", matches COLOR.white/black
    board.showPromotionDialog(event.squareTo, color, (result) => {
      if (result.type !== PROMOTION_DIALOG_RESULT_TYPE.pieceSelected) {
        render(fromFen, { push: false }); // canceled: snap back to the prior position
        return;
      }
      const letter = result.piece.charAt(1); // "wq" -> "q"
      const chosen = candidates.find((m) => m.uci === `${uci}${letter}`);
      if (!chosen) { render(fromFen, { push: false }); return; }
      history.push(fromFen);
      render(chosen.fen);
    });
    return true;
  });
}

export function initExplorer() {
  board = new Chessboard(document.getElementById("board"), {
    position: START.split(" ")[0],
    assetsUrl: "/vendor/cm-chessboard/assets/",
    // "none" draws the rank/file coordinates inline, on the squares
    // themselves (the lichess/syzygy look), instead of in a "frame" border
    // band inside the widget's visible bounds. That band carried no
    // data-square attribute, so a drag released on it -- visually still on
    // the board -- read as movedOutOfBoard and deleted the piece.
    style: { borderType: BORDER_TYPE.none },
    extensions: [{ class: PromotionDialog }],
  });
  enableBoardInput();
  buildPalette();

  document.getElementById("fen-form").addEventListener("submit", (e) => {
    e.preventDefault();
    history.push(current);
    render(document.getElementById("fen-input").value.trim());
  });
  document.getElementById("stm-select").addEventListener("change", (e) => {
    const fen = withSideToMove(current, e.target.value);
    history.push(current);
    render(fen);
  });
  document.getElementById("btn-flip").addEventListener("click", () => {
    const black = board.getOrientation() === COLOR.white;   // after the flip below
    board.setOrientation(black ? COLOR.black : COLOR.white);
    // Each tray sits on the side of the board its own colour occupies; leaving
    // them put after a flip would make them two anonymous rows of buttons.
    document.querySelector(".board-pin").classList.toggle("flipped", black);
  });
  document.getElementById("btn-back").addEventListener("click", () => {
    const prev = history.pop();
    if (prev) render(prev);
  });
  document.getElementById("btn-export-pgn").addEventListener("click", () => {
    const lines = JSON.parse(document.getElementById("lines").dataset.lines || "[]");
    const blob = new Blob([toPgn(current, lines)], { type: "application/x-chess-pgn" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "helpmate.pgn";
    a.click();
    URL.revokeObjectURL(a.href);
  });
  document.getElementById("btn-open-material").addEventListener("click", async () => {
    const material = document.getElementById("table-stats").dataset.material;
    if (!material) return;
    location.hash = encodeState({ fen: current, panel: "materials" });
    showPanel("materials");
    await whenMaterialsReady();
    const li = document.querySelector(`#material-list li[data-material="${material}"]`);
    if (li) li.click();
  });
  window.addEventListener("hashchange", () => {
    // Before the first probe there is no position to keep in sync, and
    // rendering one here would be the very network call the lazy start
    // below exists to defer. whenPanelShown fires from showPanel(), which
    // panels.js registers as a hashchange listener BEFORE this one, so a
    // hash that both activates the explorer and carries a fen (a Search
    // result click, say) has already started it by the time this runs --
    // with that same fen, so the `fen !== current` guard then finds nothing
    // to do.
    if (!started) return;
    const { fen } = decodeState(location.hash);
    if (fen && fen !== current) render(fen, { push: false });
  });

  // Deferred to the explorer panel's first activation. Probing the landing
  // position at page load meant an install with no tables painted a red
  // "no table for material 'KQvk'" over whatever screen a #panel= deep link
  // had opened -- #error-banner sits outside <main>, so it is visible from
  // every panel. See panels.js's whenPanelShown for the full rationale.
  whenPanelShown("explorer", () => {
    started = true;
    const { fen } = decodeState(location.hash);
    window.__explorerReady = render(fen || START, { push: !fen });
  });
}
