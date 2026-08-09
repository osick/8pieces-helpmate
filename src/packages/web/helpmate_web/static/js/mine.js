import { api, ApiError, DOWNLOAD_RETRY_CAP, DOWNLOAD_RETRY_MS } from "./api.js";
import { encodeState } from "./lib/state.js";
import { toFenList, toCsv } from "./lib/export.js";
import { selectedThemes, answersOnSaturated, themeOptionTitle } from "./lib/themes.js";

let rows = [];

// Monotonic token guarding the mine submit handler's 202 retry: bails out if
// a newer search has started since a retry was scheduled, so a stale poll
// from a superseded search can't overwrite #mine-status/#mine-results with
// the wrong query's results. Mirrors explorer.js's render()/materials.js's
// showStats() guard.
let mineSeq = 0;

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

async function runQuery(q, status, results, seq, retries = 0) {
  let res;
  try { res = await api.mine(q); }
  catch (err) {
    if (seq !== mineSeq) return;   // superseded by a newer search
    if (err instanceof ApiError) { status.textContent = err.hint ? `${err.message} — ${err.hint}` : err.message; return; }
    throw err;
  }
  if (seq !== mineSeq) return;     // superseded by a newer search
  if (res.status === 202) {
    if (retries >= DOWNLOAD_RETRY_CAP) {
      status.textContent = `Still downloading ${res.body.material} — this is taking longer than expected, re-running the search will resume it.`;
      return;
    }
    status.textContent = `downloading ${res.body.material}…`;
    setTimeout(() => {
      if (seq !== mineSeq) return; // user started a new search: stop retrying
      runQuery(q, status, results, seq, retries + 1);
    }, DOWNLOAD_RETRY_MS);
    return;
  }
  const b = res.body;
  rows = b.fens.map((fen) => ({ fen, dtm: Number(q.dtm), count: q.count === "" ? "" : Number(q.count) }));
  status.textContent =
    `${b.fens.length} position(s)` +
    (b.truncated ? " (truncated — raise max results for more)" : "") +
    (b.skipped_saturated ? ` · ${b.skipped_saturated} skipped (count saturated)` : "");
  if (!b.fens.length) {
    const li = document.createElement("li");
    li.className = "empty";
    li.textContent = "Nothing matches. Try a different dtm, or drop the count/starts/ends filters.";
    results.appendChild(li);
  }
  for (const fen of b.fens) {
    const li = document.createElement("li");
    li.textContent = fen;
    li.addEventListener("click", () => { location.hash = encodeState({ fen, panel: "explorer" }); });
    results.appendChild(li);
  }
}

export function initMine() {
  const form = document.getElementById("mine-form");
  const status = document.getElementById("mine-status");
  const results = document.getElementById("mine-results");

  // Populated from /v1/themes so the vocabulary always matches the server's
  // build. A failure here leaves an empty picker and no theme filtering --
  // the rest of the search screen must keep working.
  const themeSel = document.getElementById("mine-themes");
  api.themes().then(({ body }) => {
    for (const t of body.themes) {
      const o = document.createElement("option");
      o.value = t.name;
      o.textContent = t.name;
      o.title = themeOptionTitle(t);
      // Data-driven marker: any theme whose `needs` isn't "solutions" still
      // answers on positions whose stored solution count saturates, where
      // Needs::Solutions themes are silently skipped -- see themeOptionTitle.
      if (answersOnSaturated(t)) o.classList.add("theme-answers-saturated");
      themeSel.appendChild(o);
    }
  }).catch(() => { /* leave the picker empty; the numeric filters still work */ });

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const q = Object.fromEntries(new FormData(form).entries());
    q.theme = selectedThemes(themeSel);      // fromEntries would keep only one
    results.textContent = ""; rows = [];
    const bad = validate(q);
    if (bad) { status.textContent = bad; return; }
    status.textContent = "searching…";
    const seq = ++mineSeq;
    await runQuery(q, status, results, seq);
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
