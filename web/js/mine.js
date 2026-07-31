import { api, ApiError } from "./api.js";
import { encodeState } from "./lib/state.js";
import { toFenList, toCsv } from "./lib/export.js";

let rows = [];

function validate(q) {
  // Mirrors the server's rules so an obvious mistake never costs a round trip.
  // The server remains the authority; its 400 is displayed if we miss something.
  for (const k of ["starts", "ends"]) {
    if (q[k] === "" || q[k] === undefined) continue;
    const v = Number(q[k]);
    if (!Number.isInteger(v) || v < 1) return `${k} must be at least 1`;
    if (q.count !== "" && Number.isInteger(Number(q.count)) && v > Number(q.count))
      return `${k} cannot exceed count ${q.count}`;
  }
  return null;
}

export function initMine() {
  const form = document.getElementById("mine-form");
  const status = document.getElementById("mine-status");
  const results = document.getElementById("mine-results");

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const q = Object.fromEntries(new FormData(form).entries());
    results.textContent = ""; rows = [];
    const bad = validate(q);
    if (bad) { status.textContent = bad; return; }
    status.textContent = "searching…";
    let res;
    try { res = await api.mine(q); }
    catch (err) {
      if (err instanceof ApiError) { status.textContent = err.hint ? `${err.message} — ${err.hint}` : err.message; return; }
      throw err;
    }
    if (res.status === 202) { status.textContent = `downloading ${res.body.material}…`; return; }
    const b = res.body;
    rows = b.fens.map((fen) => ({ fen, dtm: Number(q.dtm), count: q.count === "" ? "" : Number(q.count) }));
    status.textContent =
      `${b.fens.length} position(s)` +
      (b.truncated ? " (truncated)" : "") +
      (b.skipped_saturated ? ` · ${b.skipped_saturated} skipped (count saturated)` : "");
    for (const fen of b.fens) {
      const li = document.createElement("li");
      li.textContent = fen;
      li.addEventListener("click", () => { location.hash = encodeState({ fen, panel: "explorer" }); });
      results.appendChild(li);
    }
  });

  const download = (text, name, type) => {
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([text], { type }));
    a.download = name; a.click(); URL.revokeObjectURL(a.href);
  };
  document.getElementById("btn-export-fens")
    .addEventListener("click", () => download(toFenList(rows.map((r) => r.fen)), "helpmate-fens.txt", "text/plain"));
  document.getElementById("btn-export-csv")
    .addEventListener("click", () => download(toCsv(rows), "helpmate-mine.csv", "text/csv"));
}
