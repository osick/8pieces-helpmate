import { Chessboard, INPUT_EVENT_TYPE, COLOR } from "../vendor/cm-chessboard/Chessboard.js";
import { api, ApiError } from "./api.js";
import { encodeState, decodeState } from "./lib/state.js";
import { toPgn } from "./lib/export.js";

const START = "8/7k/5K2/8/8/8/8/6Q1 b - - 0 1";
let board = null;
let current = START;
let lastMoves = [];      // the move list from the last /v1/moves call, for drag input
const history = [];

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

async function render(fen, { push = true } = {}) {
  current = fen;
  document.getElementById("fen-input").value = fen;
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
  if (push) location.hash = encodeState({ fen, panel: "explorer" });

  const summary = document.getElementById("position-summary");
  const moveList = document.getElementById("move-list");
  const linesEl = document.getElementById("lines");
  moveList.textContent = ""; linesEl.textContent = "";

  let res;
  try {
    res = await api.moves(fen);
  } catch (err) {
    if (err instanceof ApiError) { showError(err); summary.textContent = ""; return; }
    throw err;
  }
  if (res.status === 202) {
    showInfo(`downloading ${res.body.material}…`);
    setTimeout(() => render(fen, { push: false }), 1500);
    return;
  }
  clearBanner();

  const b = res.body;
  lastMoves = b.moves;
  summary.textContent = b.solvable === false
    ? "unsolvable"
    : `dtm ${b.dtm} (${b.notation}) · ${b.count} optimal line(s)` +
      (b.flipped ? " · colors flipped" : "");

  for (const m of b.moves) {
    const li = document.createElement("li");
    li.textContent = m.solvable ? `${m.san} → ${m.notation}` : `${m.san} → –`;
    li.className = m.optimal ? "optimal" : (m.solvable ? "" : "dead");
    li.dataset.san = m.san;
    li.addEventListener("click", () => { history.push(current); render(m.fen); });
    moveList.appendChild(li);
  }

  if (b.solvable !== false) {
    try {
      const ls = await api.line(fen, true);
      for (const line of ls.body.lines) {
        const li = document.createElement("li");
        li.textContent = line.join(" ");
        linesEl.appendChild(li);
      }
      linesEl.dataset.lines = JSON.stringify(ls.body.lines);
    } catch (err) { if (!(err instanceof ApiError)) throw err; }
  }
}

export function initExplorer() {
  board = new Chessboard(document.getElementById("board"), {
    position: START.split(" ")[0],
    assetsUrl: "/vendor/cm-chessboard/assets/",
    style: { borderType: "frame" },
  });

  // Dragging a piece plays the corresponding legal move, when there is one.
  // The board is a view over the server's move list: we never invent a move
  // client-side, we look up the drag in what /v1/moves returned.
  board.enableMoveInput((event) => {
    if (event.type !== INPUT_EVENT_TYPE.validateMoveInput) return true;
    const uci = `${event.squareFrom}${event.squareTo}`;
    const hit = (lastMoves || []).find((m) => m.uci === uci || m.uci.startsWith(uci));
    if (!hit) return false;               // not a legal move: snap back
    history.push(current);
    render(hit.fen);
    return true;
  });

  document.getElementById("fen-form").addEventListener("submit", (e) => {
    e.preventDefault();
    history.push(current);
    render(document.getElementById("fen-input").value.trim());
  });
  document.getElementById("btn-flip").addEventListener("click", () => {
    board.setOrientation(board.getOrientation() === COLOR.white ? COLOR.black : COLOR.white);
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
  window.addEventListener("hashchange", () => {
    const { fen } = decodeState(location.hash);
    if (fen && fen !== current) render(fen, { push: false });
  });

  const { fen } = decodeState(location.hash);
  window.__explorerReady = render(fen || START, { push: !fen });
}
