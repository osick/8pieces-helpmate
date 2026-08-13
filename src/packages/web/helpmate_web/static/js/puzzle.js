// The puzzle screen: a session of `SESSION_SIZE` helpmates drawn from
// puzzles.epd, solved by dragging out the WHOLE line -- both colours. A
// helpmate is cooperative, so proving you know the solution means playing
// Black's moves as well as White's, not just answering "what does White
// play".
//
// This is the explorer's board asking a different question, not a second
// editor: same board construction (assetsUrl, BORDER_TYPE.none), same
// rail/readout markup, but no palette, no relocation, no FEN box -- only
// legal drags are ever accepted, and only the one expected at the current
// ply is graded correct.
//
// Its own module-level state (board, current position, the move list the
// board's drag input trusts) is deliberately separate from explorer.js's
// `board`/`current`/`lastMoves`/`history` -- two independent Chessboard
// instances that must never read or write each other's state. render() in
// explorer.js is never called from here, and nothing here is imported by it.
import { Chessboard, INPUT_EVENT_TYPE, BORDER_TYPE } from "../vendor/cm-chessboard/Chessboard.js";
import {
  PromotionDialog,
  PROMOTION_DIALOG_RESULT_TYPE,
} from "../vendor/cm-chessboard/extensions/promotion-dialog/PromotionDialog.js";
import { api, ApiError, DOWNLOAD_RETRY_CAP, DOWNLOAD_RETRY_MS } from "./api.js";
import { el } from "./stats-view.js";
import { whenPanelShown } from "./panels.js";
import { splitFen } from "./lib/fen.js";
import { parseEpd, pickSession, gradeMove, materialOf } from "./lib/puzzles.js";

const SESSION_SIZE = 10;

let board = null;

// The full parsed puzzle set, fetched once and kept for every future
// session -- a "start another" click draws a fresh SESSION_SIZE without a
// second network round trip.
let allPuzzles = null;

// The materials this installation actually has tables for (a Set of strings
// like "KQvk"), fetched once via /v1/materials and reused across sessions --
// same caching shape as allPuzzles, and for the same reason: a puzzle whose
// material nobody has generated is not a harder puzzle, it is a 404. null
// means "not fetched yet"; an empty Set (fetch failed, or genuinely nothing
// installed) is treated the same as "nothing available" below, which is the
// safe direction to fail in -- showing a puzzle we can't confirm is playable
// risks the exact dead-screen defect this filter exists to prevent.
let availableMaterials = null;

let session = [];        // this run's SESSION_SIZE puzzles, easiest first
let idx = 0;              // index into session
let sessionDone = false;
let solved = 0;           // puzzles of THIS session played out to mate, for the closing line

let boardFen = null;      // this screen's own current position -- unrelated to explorer's `current`
let solutionSan = [];     // the SAN plies of the one solution api.line(fen) returned
let plyEls = [];           // one <span class="ply"> per solutionSan entry, in order
let plyIndex = 0;          // the next ply the player must supply
let errors = 0;
let budget = 1;            // errors ABOVE this reveal the rest of the line
let revealed = false;
let lastMoves = [];        // this screen's own /v1/moves cache -- unrelated to explorer's

// Monotonic token guarding a puzzle's in-flight async work: loadPuzzle()
// bumps it, and grade()/reveal() bail out after an await if a newer puzzle
// has since loaded (e.g. a fast double-click on "Next puzzle") -- the same
// discipline explorer.js's renderSeq applies to render().
let loadSeq = 0;

function setPromptLoading() {
  document.getElementById("puzzle-prompt").textContent = "Loading…";
}

function buildLine(sanList) {
  const ol = document.getElementById("puzzle-line");
  ol.textContent = "";
  ol.classList.remove("revealed");
  plyEls = [];
  // Paired into one row per move number -- nine rows even at the hardest
  // tier's eighteen plies, not a wall of eighteen bare lines.
  for (let i = 0; i < sanList.length; i += 2) {
    const row = el("li", "move-row");
    row.appendChild(el("span", "move-no", `${i / 2 + 1}.`));
    for (let j = i; j < Math.min(i + 2, sanList.length); j++) {
      const ply = el("span", "ply");
      ply.dataset.ply = String(j);
      row.appendChild(ply);
      plyEls.push(ply);
    }
    ol.appendChild(row);
  }
}

// Mirrors explorer.js's/materials.js's own 202-retry loop (same
// DOWNLOAD_RETRY_CAP/MS policy): a puzzle can land on material nobody has
// asked for yet, and "still downloading" is routine, not an error.
async function movesWithRetry(fen, seq, retries = 0) {
  let res;
  try { res = await api.moves(fen); }
  catch (err) {
    // Staleness is checked on the FAILURE path too, not just the success
    // one. A puzzle on a remote table enters the 202 poll; the user clicks
    // "Next puzzle" and the following puzzle loads; then the abandoned
    // retry finally rejects (a failed download is a real 500 from
    // /v1/moves). Without this guard that rejection reached showLoadError()
    // and overwrote the prompt of the puzzle now on screen, naming a
    // material that is not on the board.
    if (seq !== loadSeq) return { stale: true };
    return { err };
  }
  if (seq !== loadSeq) return { stale: true };
  if (res.status !== 202) return { res };
  if (retries >= DOWNLOAD_RETRY_CAP) {
    return { err: { message: "still downloading", hint: "this is taking longer than expected -- Next puzzle will try again" } };
  }
  document.getElementById("puzzle-prompt").textContent = `downloading ${res.body.material}…`;
  await new Promise((r) => { setTimeout(r, DOWNLOAD_RETRY_MS); });
  if (seq !== loadSeq) return { stale: true };
  return movesWithRetry(fen, seq, retries + 1);
}

function showLoadError(err) {
  document.getElementById("puzzle-prompt").textContent =
    err instanceof ApiError
      ? (err.hint ? `${err.message} — ${err.hint}` : err.message)
      : (err && err.hint ? `${err.message} — ${err.hint}` : (err && err.message) || "could not load this puzzle");
}

async function loadPuzzle() {
  const seq = ++loadSeq;
  const puzzle = session[idx];
  boardFen = puzzle.fen;
  solutionSan = [];
  plyEls = [];
  plyIndex = 0;
  errors = 0;
  revealed = false;

  const correction = document.getElementById("puzzle-correction");
  correction.hidden = true;
  document.getElementById("puzzle-solved").hidden = true;
  document.getElementById("puzzle-line").textContent = "";
  // Honest about a thin install: a session shorter than SESSION_SIZE (too
  // few materials on hand for a full ladder) says so plainly here, rather
  // than silently presenting fewer puzzles as if a full ten were on offer.
  document.getElementById("puzzle-progress").textContent = session.length < SESSION_SIZE
    ? `Puzzle ${idx + 1} of ${session.length} (only ${session.length} of this installation's tables match the puzzle set)`
    : `Puzzle ${idx + 1} of ${session.length}`;
  setPromptLoading();

  const p = board.setPosition(puzzle.fen.split(" ")[0], true);
  if (p && typeof p.catch === "function") p.catch(() => { /* a malformed puzzle FEN would 400 below anyway */ });

  const outcome = await movesWithRetry(puzzle.fen, seq);
  if (outcome.stale) return;               // superseded by a newer loadPuzzle()
  if (outcome.err) { showLoadError(outcome.err); return; }
  const movesRes = outcome.res;

  let lineRes;
  try {
    lineRes = await api.line(puzzle.fen);
  } catch (err) {
    if (seq !== loadSeq) return;           // superseded by a newer loadPuzzle()
    showLoadError(err);
    return;
  }
  if (seq !== loadSeq) return;             // superseded by a newer loadPuzzle()

  lastMoves = movesRes.body.moves || [];
  solutionSan = (lineRes.body.lines && lineRes.body.lines[0]) || [];
  const side = splitFen(puzzle.fen).stm === "b" ? "Black" : "White";
  document.getElementById("puzzle-prompt").textContent =
    `${movesRes.body.material} · ${movesRes.body.notation} · one solution — ${side} to move`;
  buildLine(solutionSan);
}

// How many men a material name stands for -- "KQBvk" is 4. The "v" is a
// separator, not a piece, so it does not count.
function menIn(material) {
  return material.length - 1;
}

function sayNoPuzzlesMatch() {
  // Not "no puzzles" -- name what to do. Sorted so the message is stable
  // across sessions and easy to scan, not a re-shuffled wall each time.
  const materials = [...new Set(allPuzzles.map((p) => materialOf(p.fen)))].sort();
  // Recommend the CHEAPEST table in the set, not the alphabetically first:
  // sorted()[0] is KBBvkbb, a 6-man table that is hours of compute and tens
  // of gigabytes, offered to someone who has generated nothing at all. The
  // set also contains 4-man closures (KQBvk, KQPvk, KRvkp, ...) that finish
  // in seconds, and one of those is what a first table should be. Ties are
  // broken alphabetically so the advice is stable, not a different name each
  // reload.
  const example = [...materials]
    .sort((a, b) => menIn(a) - menIn(b) || a.localeCompare(b))[0] || "KQvk";
  document.getElementById("puzzle-progress").textContent = "";
  document.getElementById("puzzle-prompt").textContent =
    `none of this installation's tables match the shipped puzzle set. It uses: ${materials.join(", ")}. `
    + `Generate one -- e.g. \`helpmate gen ${example} --tables <dir>\` -- then reload this screen.`;
  document.getElementById("puzzle-line").textContent = "";
}

async function startSession() {
  sessionDone = false;
  solved = 0;
  document.getElementById("btn-puzzle-next").textContent = "Next puzzle";
  document.getElementById("btn-puzzle-solution").disabled = false;

  if (allPuzzles === null) {
    try {
      allPuzzles = parseEpd(await api.puzzles());
    } catch {
      // Network failure: degrade to the message below. Not because a throw
      // here would take another screen down -- init*() are async, so a
      // rejection cannot stop a sibling -- but because an unhandled
      // rejection leaves this screen sitting on "Loading…" forever with
      // nothing on it saying why.
      allPuzzles = [];
    }
  }
  if (!allPuzzles.length) {
    document.getElementById("puzzle-progress").textContent = "";
    document.getElementById("puzzle-prompt").textContent = "could not load the puzzle set";
    document.getElementById("puzzle-line").textContent = "";
    return;
  }

  if (availableMaterials === null) {
    try {
      const res = await api.materials();
      availableMaterials = new Set((res.body.materials || []).map((m) => m.material));
    } catch {
      availableMaterials = new Set();   // couldn't ask: the safe default is "nothing confirmed available"
    }
  }

  const isAvailable = (p) => availableMaterials.has(materialOf(p.fen));
  session = pickSession(allPuzzles, SESSION_SIZE, Math.random, isAvailable);
  if (!session.length) {
    sayNoPuzzlesMatch();
    return;
  }
  idx = 0;
  await loadPuzzle();
}

// The closing line reports what actually happened. "Nice work — 10 of 10"
// used to be printed unconditionally: after a session where every ply was
// wrong, and -- because an EMPTY session also reaches this via the Next
// button -- as "Nice work — 0 of 0" on an installation that had no playable
// puzzle to offer in the first place. Congratulating someone for solving
// nothing is the fastest way to make every other number on the screen
// untrustworthy, so each outcome gets its own sentence.
function sessionVerdict(n) {
  if (solved === n) return "Nice work — every one solved. Start another session?";
  if (solved === 0) return "None solved this time. Start another session?";
  return `${solved} of ${n} solved. Start another session?`;
}

function showSessionDone() {
  document.getElementById("puzzle-progress").textContent =
    `Session complete — ${solved} of ${session.length} solved`;
  document.getElementById("puzzle-prompt").textContent = sessionVerdict(session.length);
  document.getElementById("puzzle-line").textContent = "";
  document.getElementById("puzzle-correction").hidden = true;
  document.getElementById("puzzle-solved").hidden = true;
  document.getElementById("btn-puzzle-next").textContent = "New session";
  document.getElementById("btn-puzzle-solution").disabled = true;
}

// Its own element, not a reuse of #puzzle-correction: that element carries
// "here is the move you missed", a distinct meaning from "you finished this
// puzzle" -- a live region that changes what it means mid-solve is exactly
// the "nothing quietly does double duty" rule, and confusing to anyone
// hitting it via assistive tech.
async function finishPuzzle() {
  solved++;
  document.getElementById("puzzle-correction").hidden = true;
  const box = document.getElementById("puzzle-solved");
  // Unhide BEFORE writing the text: #puzzle-solved is a role="status" live
  // region, and a change made while the element is still hidden is not
  // announced.
  box.hidden = false;
  box.textContent = "Solved.";
}

// Plays out the remaining plies on the board and in the line, without
// grading them -- either "Show solution" was clicked, or the error budget
// was just exceeded. Idempotent: a second reveal() (e.g. "Show solution"
// after the budget already tripped it) is a no-op.
async function reveal() {
  if (revealed || !solutionSan.length) return;
  revealed = true;
  const seq = loadSeq;
  document.getElementById("puzzle-line").classList.add("revealed");
  for (let i = plyIndex; i < solutionSan.length; i++) {
    plyEls[i].classList.add("revealed");
    plyEls[i].textContent = solutionSan[i];
  }
  document.getElementById("puzzle-correction").hidden = true;

  // Walk the rest of the line move by move -- api.line gives SAN only, so
  // each ply's FEN is recovered the same way grading recovers its UCI:
  // matching that ply's SAN against /v1/moves for the position reached so
  // far. Bounded by the line's own length (18 plies at the hardest tier).
  try {
    let fen = boardFen;
    for (let i = plyIndex; i < solutionSan.length; i++) {
      const r = await api.moves(fen);
      if (seq !== loadSeq) return;   // superseded by a newer loadPuzzle()
      const m = (r.body.moves || []).find((mm) => mm.san === solutionSan[i]);
      if (!m) break;   // a stored line the current tables can't replay: stop where we can still trust the board
      fen = m.fen;
    }
    if (seq !== loadSeq) return;     // superseded by a newer loadPuzzle()
    boardFen = fen;
    const p = board.setPosition(boardFen.split(" ")[0], true);
    if (p && typeof p.catch === "function") p.catch(() => {});
  } catch {
    // The board stays wherever grading left it; the line list already shows
    // every remaining SAN, which is the part of "reveal" that must not fail.
  }
  plyIndex = solutionSan.length;
}

// The one place correctness is decided. Synchronous and side-effect-only on
// the DOM/state that doesn't require a network round trip, so a drag's
// validateMoveInput callback (which must answer true/false synchronously,
// to tell cm-chessboard whether to let the piece land or snap back) can call
// it directly. Returns true/false, or null when there is no active ply to
// grade (revealed, or the puzzle is already solved).
function judge(uci) {
  if (revealed || !solutionSan.length || plyIndex >= solutionSan.length) return null;
  const expectedSan = solutionSan[plyIndex];
  const match = lastMoves.find((m) => m.san === expectedSan);
  const correct = Boolean(match) && gradeMove(match.uci, uci);
  const li = plyEls[plyIndex];
  const correction = document.getElementById("puzzle-correction");
  if (correct) {
    li.classList.add("correct");
    li.textContent = expectedSan;
    correction.hidden = true;
    plyIndex++;
    boardFen = match.fen;
  } else {
    li.classList.add("wrong");
    errors++;
    correction.hidden = false;
    correction.textContent = `Correct move: ${expectedSan}`;
  }
  return correct;
}

// judge()'s async tail: advance the board and refetch the move list a
// correct answer needs for the next ply, or reveal the line once the error
// budget is exceeded.
async function afterJudge(correct) {
  if (correct) {
    const p = board.setPosition(boardFen.split(" ")[0], true);
    if (p && typeof p.catch === "function") p.catch(() => {});
    if (plyIndex >= solutionSan.length) { await finishPuzzle(); return; }
    const seq = loadSeq;
    try {
      const r = await api.moves(boardFen);
      if (seq !== loadSeq) return;   // superseded by a newer loadPuzzle()
      lastMoves = r.body.moves || [];
    } catch {
      if (seq !== loadSeq) return;
      lastMoves = [];
    }
  } else if (errors > budget) {
    await reveal();
  }
}

// window.__puzzlePlay(uci) and window.__puzzleSetBudget(n) are deliberate
// TEST HOOKS, not part of the normal play path -- driving a deliberately
// WRONG move through a real drag is unreliable in Playwright (there is
// nothing to drop the piece onto that represents "the wrong square" more
// than any other), and it is the grading logic itself, not drag mechanics,
// that the UI tests exist to pin. Both funnel through the exact same
// judge()/afterJudge() a real drag uses below, so the hook exercises the
// real grading path rather than a parallel one built only for tests.
async function grade(uci) {
  const correct = judge(uci);
  if (correct === null) return;
  await afterJudge(correct);
}

function enableBoardInput() {
  board.enableMoveInput((event) => {
    if (event.type !== INPUT_EVENT_TYPE.validateMoveInput) return true;
    if (revealed || !solutionSan.length || plyIndex >= solutionSan.length) return false;

    const uci = `${event.squareFrom}${event.squareTo}`;
    const exact = lastMoves.find((m) => m.uci === uci);
    if (exact) {
      const correct = judge(exact.uci);
      afterJudge(correct);
      return correct;   // wrong: reject the drag outright, the piece snaps back and the position is untouched
    }

    // A drag that is a legal move's uci PREFIX is an underpromotion choice
    // (e.g. "e7e8" before the piece is picked) -- the same convention
    // explorer.js's own move-matching uses.
    const candidates = lastMoves.filter(
      (m) => m.uci.length === uci.length + 1 && m.uci.startsWith(uci)
    );
    if (candidates.length === 0) return false;   // not a legal move here: snap back
    if (candidates.length === 1) {
      const correct = judge(candidates[0].uci);
      afterJudge(correct);
      return correct;
    }

    // Several underpromotion pieces are legal: ask which one, and grade
    // whichever is chosen. This drag itself is rejected outright rather than
    // animated -- grade() drives the board from boardFen once a piece is
    // picked, instead of racing cm-chessboard's own animation of a move that
    // was never confirmed.
    const color = event.piece.charAt(0);   // "wp" -> "w", matches COLOR.white/black
    board.showPromotionDialog(event.squareTo, color, (result) => {
      if (result.type !== PROMOTION_DIALOG_RESULT_TYPE.pieceSelected) return;
      const chosen = candidates.find((m) => m.uci === `${uci}${result.piece.charAt(1)}`);
      if (chosen) grade(chosen.uci);
    });
    return false;
  });
}

export async function initPuzzles() {
  board = new Chessboard(document.getElementById("puzzle-board"), {
    position: "8/8/8/8/8/8/8/8",
    assetsUrl: "/vendor/cm-chessboard/assets/",
    // Same as explorer.js's own board: "none" draws coordinates inline, on
    // the squares themselves, instead of in a frame border band that a drop
    // could land on without a data-square attribute to hit-test against.
    style: { borderType: BORDER_TYPE.none },
    extensions: [{ class: PromotionDialog }],
  });
  enableBoardInput();

  document.getElementById("btn-puzzle-solution").addEventListener("click", () => { reveal(); });
  document.getElementById("btn-puzzle-next").addEventListener("click", async () => {
    // An empty session (nothing on this installation matched the puzzle set,
    // or the set itself failed to load) has no "next" and no result to
    // report -- retry it instead of falling through to the completion
    // screen, which would replace the message explaining WHY there is
    // nothing with a summary of a session that never ran.
    if (sessionDone || !session.length) { await startSession(); return; }
    idx++;
    if (idx >= session.length) {
      sessionDone = true;
      showSessionDone();
      return;
    }
    await loadPuzzle();
  });

  window.__puzzlePlay = (uci) => grade(uci);
  window.__puzzleSetBudget = (n) => { budget = Number(n); };

  // Deferred to the puzzles panel's first activation. startSession() fetches
  // the puzzle set, the material catalog and then a whole puzzle's /v1/moves
  // + /v1/line -- and on an install with a remote table chain that last call
  // answers 202 and STARTS A DOWNLOAD, which movesWithRetry then polls for up
  // to a minute. Doing that at page load meant every visit to the dashboard
  // pulled a table down for a screen nobody had opened. See panels.js's
  // whenPanelShown.
  whenPanelShown("puzzles", () => { startSession(); });
}
