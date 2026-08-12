import {
  Chessboard, INPUT_EVENT_TYPE, COLOR, POINTER_EVENTS,
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
import { renderStats } from "./stats-view.js";
import { showPanel } from "./panels.js";
import { squareFromTarget, exceedsDragThreshold } from "./lib/board-edit.js";

const START = "8/7k/5K2/8/8/8/8/6Q1 b - - 0 1";
const SPRITE = "/vendor/cm-chessboard/assets/pieces/standard.svg";
const PALETTE = ["wk", "wq", "wr", "wb", "wn", "wp", "bk", "bq", "br", "bb", "bn", "bp"];
// The fourth arming state. A piece name places, "" erases, null plays -- and
// this drags what is already on the board. It is a distinct value rather than
// a flag because click-to-place and drag-to-rearrange both bind pointerdown,
// so exactly one of them may be live at a time.
const ARRANGE = "arrange";

let board = null;
let current = START;
let lastMoves = [];      // the move list from the last /v1/moves call, for drag input
// The armed palette entry: a piece name to place, "" to erase, or null when
// the board is in play mode (drag = play a move). Editing and playing are
// mutually exclusive on the same pointer, so arming swaps the board's input.
let armed = null;
const history = [];

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
      if (res.status !== 200) { band.hidden = true; bandMaterial = null; return; }
      statsCache.set(material, res.body);
    } catch {
      band.hidden = true; bandMaterial = null; return;   // never break the board on context
    }
  }
  if (bandMaterial !== material) return;                 // superseded while awaiting
  renderStats(body, statsCache.get(material), { idPrefix: "tbl-", samples: false });
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

// Reflect a FEN in the controls without touching the API. Used both by
// render() and by the editor, which deliberately does not probe on every
// placement -- a half-built position is illegal by definition and an error
// banner per placed piece would be noise, not information.
function syncControls(fen) {
  document.getElementById("fen-input").value = fen;
  document.getElementById("stm-select").value = splitFen(fen).stm;
}

// #move-list is a <div> of <section class="move-group">, not a <ul>. Seven UI
// tests use `#move-list li` as their "the page is ready" idiom and two COUNT
// it, so a group header must never be an <li> -- it is the section's <h3>,
// outside the <ul>. `#move-list li` then still selects exactly the move rows.
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

    const ul = document.createElement("ul");
    for (const m of g.moves) {
      const li = document.createElement("li");
      li.className = moveClass(m);
      li.dataset.san = m.san;
      const san = document.createElement("span");
      san.className = "san";
      san.textContent = m.san;
      const badge = document.createElement("span");
      badge.className = "badge";
      badge.textContent = moveBadge(m);
      li.append(san, badge);
      // Every row is clickable, including the dead ones: walking into a
      // position with no helpmate is a legitimate thing to want to look at,
      // and that is the behaviour the list has today.
      li.addEventListener("click", () => { history.push(current); render(m.fen); });
      ul.appendChild(li);
    }
    sec.append(h, ul);
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
  moveList.textContent = ""; linesEl.textContent = ""; themesEl.textContent = "";
  linesEl.dataset.lines = "[]";

  // A position with a missing or duplicated king is one the editor produces
  // on the way to a real position; say so plainly instead of spending a round
  // trip to be told "invalid FEN".
  const kings = kingProblem(splitFen(fen).placement);
  if (kings) {
    summary.textContent = kings;
    summary.classList.add("muted");
    clearBanner();
    lastMoves = [];
    showTableStats(null);
    return;
  }

  let res;
  try {
    res = await api.moves(fen);
  } catch (err) {
    if (seq !== renderSeq) return;   // superseded by a newer render()
    if (err instanceof ApiError) { showError(err); summary.textContent = ""; return; }
    throw err;
  }
  if (seq !== renderSeq) return;     // superseded by a newer render()

  if (res.status === 202) {
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
    }).catch(() => { /* annotation is a nicety; never break the board on it */ });
  }

  renderMoveList(moveList, b.moves);

  if (b.solvable !== false) {
    try {
      const ls = await api.line(fen, true);
      if (seq !== renderSeq) return; // superseded by a newer render()
      for (const line of ls.body.lines) {
        const li = document.createElement("li");
        li.textContent = line.join(" ");
        linesEl.appendChild(li);
      }
      linesEl.dataset.lines = JSON.stringify(ls.body.lines);
    } catch (err) {
      if (seq !== renderSeq) return; // superseded by a newer render()
      if (!(err instanceof ApiError)) throw err;
    }
  }
}

// ---- position editor -------------------------------------------------

// Read the placement back off the board and evaluate it. Called when the
// user leaves edit mode, not on every click.
function commitBoard() {
  const fen = withPlacement(current, board.getPosition());
  // Arming and disarming without touching a square must not cost a request
  // or leave a duplicate entry for Back to walk through. `current` already
  // tracks each placement, so an unchanged FEN means nothing was edited --
  // but the panel still has to be redrawn, because entering edit mode
  // retired the previous value.
  if (fen !== current) history.push(current);
  render(fen, { push: fen !== current });
}

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
        // Past the threshold this is a drag, so arm the piece (which puts the
        // board in edit mode) and stop the click handler from also firing.
        if (armed !== piece) setArmed(piece);
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
      btn.dataset.dragged = "1";
      const square = squareFromTarget(document.elementFromPoint(e.clientX, e.clientY));
      if (!square) return;                      // dropped off the board: no-op
      board.setPiece(square, piece).then(() => {
        const fen = withPlacement(current, board.getPosition());
        current = fen;
        syncControls(fen);
      });
    };

    btn.setPointerCapture(down.pointerId);
    btn.addEventListener("pointermove", move);
    btn.addEventListener("pointerup", up);
    btn.addEventListener("pointercancel", up);
  });
}

function onSquareClick(event) {
  if (armed === null || !event.square) return;
  // setPiece is async; the board is the source of truth for the placement, so
  // update the FEN box only once it has actually applied.
  board.setPiece(event.square, armed || null).then(() => {
    const fen = withPlacement(current, board.getPosition());
    current = fen;
    syncControls(fen);
  });
}

// `commit` is false when something else is about to set the position anyway
// (typing a FEN, following a link): committing there would spend a request on
// a position the very next line replaces, and push a bogus history entry.
function setArmed(piece, { commit = true } = {}) {
  const wasEditing = armed !== null;
  armed = piece;
  for (const btn of document.querySelectorAll("#palette button"))
    btn.setAttribute("aria-pressed", String(btn.dataset.piece === piece && piece !== null));

  const done = document.getElementById("btn-done-editing");

  // Exactly one input binding is live at a time. Rebinding unconditionally is
  // cheaper to reason about than working out which transitions need which
  // call, and cm-chessboard's disable* calls are safe when nothing is bound.
  board.disableSquareSelect(POINTER_EVENTS.pointerdown);
  board.disableMoveInput();

  if (armed === null) {
    enableDragToPlay();
    done.hidden = true;
    if (wasEditing && commit) commitBoard();
    return;
  }

  if (armed === ARRANGE) enableDragToEdit();
  else board.enableSquareSelect(POINTER_EVENTS.pointerdown, onSquareClick);
  done.hidden = false;

  if (!wasEditing) {
    // The previous position's value belongs to a position that no longer
    // exists. Leaving it on screen while pieces move around would present a
    // stale dtm as the current one; say what is happening instead.
    const summary = document.getElementById("position-summary");
    summary.textContent = "editing — press Done to evaluate";
    summary.classList.add("muted");
    document.getElementById("position-themes").textContent = "";
    document.getElementById("move-list").textContent = "";
    const linesEl = document.getElementById("lines");
    linesEl.textContent = ""; linesEl.dataset.lines = "[]";
    lastMoves = [];
    showTableStats(null);
  }
}

function buildPalette() {
  const box = document.getElementById("palette-pieces");
  for (const piece of PALETTE) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.dataset.piece = piece;
    btn.setAttribute("aria-pressed", "false");
    btn.title = piece;
    btn.setAttribute("aria-label", piece);
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", "0 0 40 40");
    const use = document.createElementNS("http://www.w3.org/2000/svg", "use");
    use.setAttribute("href", `${SPRITE}#${piece}`);
    svg.appendChild(use);
    btn.appendChild(svg);
    // Clicking the armed piece again puts the board back in play mode, so a
    // round trip through the palette is never needed to resume exploring.
    btn.addEventListener("click", () => {
      if (btn.dataset.dragged === "1") { delete btn.dataset.dragged; return; }
      setArmed(armed === piece ? null : piece);
    });
    enablePaletteDrag(btn, piece);
    box.appendChild(btn);
  }
  const erase = document.getElementById("btn-erase");
  erase.setAttribute("aria-pressed", "false");
  erase.addEventListener("click", () => setArmed(armed === "" ? null : ""));
  const arrange = document.getElementById("btn-arrange");
  arrange.setAttribute("aria-pressed", "false");
  arrange.addEventListener("click", () => setArmed(armed === ARRANGE ? null : ARRANGE));
  document.getElementById("btn-clear-board").addEventListener("click", () => {
    board.setPosition(EMPTY_PLACEMENT, false).then(() => {
      const fen = composeFen(EMPTY_PLACEMENT, splitFen(current).stm);
      current = fen;
      syncControls(fen);
      if (armed === null) render(fen);
    });
  });
}

// ---- board input -----------------------------------------------------

// While editing, a drag means "move this piece there" (any square, legal or
// not) and a drag off the board means "remove it". cm-chessboard raises both;
// we simply stopped ignoring them.
function enableDragToEdit() {
  board.enableMoveInput((event) => {
    if (event.type === INPUT_EVENT_TYPE.validateMoveInput) return true;
    if (event.type === INPUT_EVENT_TYPE.moveInputCanceled
        && event.reason === MOVE_CANCELED_REASON.movedOutOfBoard) {
      board.setPiece(event.squareFrom, null).then(syncFromBoard);
      return;
    }
    if (event.type === INPUT_EVENT_TYPE.moveInputFinished) syncFromBoard();
    return true;
  });
}

function syncFromBoard() {
  const fen = withPlacement(current, board.getPosition());
  current = fen;
  syncControls(fen);
}

function enableDragToPlay() {
  // Dragging a piece plays the corresponding legal move, when there is one.
  // The board is a view over the server's move list: we never invent a move
  // client-side, we look up the drag in what /v1/moves returned.
  //
  // A drag only tells us from/to squares (a 4-char uci prefix); it never
  // tells us which piece to promote to. If several promotion moves share
  // that prefix (e.g. e7e8q/e7e8r/e7e8b/e7e8n) we must not guess -- show
  // the vendored promotion dialog and play exactly the uci the user picks.
  board.enableMoveInput((event) => {
    if (event.type !== INPUT_EVENT_TYPE.validateMoveInput) return true;
    const uci = `${event.squareFrom}${event.squareTo}`;
    const moves = lastMoves || [];

    const exact = moves.find((m) => m.uci === uci);
    if (exact) {
      history.push(current);
      render(exact.fen);
      return true;
    }

    const candidates = moves.filter(
      (m) => m.uci.length === uci.length + 1 && m.uci.startsWith(uci)
    );
    if (candidates.length === 0) return false; // not a legal move: snap back

    if (candidates.length === 1) {
      history.push(current);
      render(candidates[0].fen);
      return true;
    }

    // Several underpromotion choices are legal: ask the user which piece.
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
    // Let the piece land visually now; the dialog callback above resolves
    // the exact move (or snaps back to fromFen if the user cancels).
    return true;
  });
}

export function initExplorer() {
  board = new Chessboard(document.getElementById("board"), {
    position: START.split(" ")[0],
    assetsUrl: "/vendor/cm-chessboard/assets/",
    style: { borderType: "frame" },
    extensions: [{ class: PromotionDialog }],
  });
  enableDragToPlay();
  buildPalette();

  document.getElementById("fen-form").addEventListener("submit", (e) => {
    e.preventDefault();
    setArmed(null, { commit: false });    // typing a FEN ends any editing session
    history.push(current);
    render(document.getElementById("fen-input").value.trim());
  });
  document.getElementById("stm-select").addEventListener("change", (e) => {
    const fen = withSideToMove(current, e.target.value);
    if (armed !== null) { current = fen; syncControls(fen); return; }
    history.push(current);
    render(fen);
  });
  document.getElementById("btn-flip").addEventListener("click", () => {
    board.setOrientation(board.getOrientation() === COLOR.white ? COLOR.black : COLOR.white);
  });
  document.getElementById("btn-back").addEventListener("click", () => {
    const prev = history.pop();
    if (prev) render(prev);
  });
  document.getElementById("btn-done-editing").addEventListener("click", () => setArmed(null));
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
    const { fen } = decodeState(location.hash);
    if (fen && fen !== current) {
      setArmed(null, { commit: false }); // a link wins over an unfinished edit
      render(fen, { push: false });
    }
  });

  const { fen } = decodeState(location.hash);
  window.__explorerReady = render(fen || START, { push: !fen });
}
