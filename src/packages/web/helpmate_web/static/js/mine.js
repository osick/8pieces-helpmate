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

// The server's own budget, so the countdown is not a number hardcoded here.
// 30 matches main.py's --mine-timeout default and is only ever the fallback
// for a health call that failed.
let budgetSeconds = 30;
let inFlight = null;     // the AbortController of the running search
let ticker = null;       // the elapsed-time interval

function startTicker(status) {
  const began = Date.now();
  const tick = () => {
    const secs = Math.floor((Date.now() - began) / 1000);
    status.textContent = `searching… ${secs}s of ${budgetSeconds}s`;
  };
  tick();
  ticker = setInterval(tick, 1000);
}

function stopTicker() {
  if (ticker !== null) { clearInterval(ticker); ticker = null; }
}

// Which controls are live. One function so the two buttons can never
// disagree about whether a search is running.
function setBusy(busy) {
  document.querySelector("#mine-form button[type=submit]").hidden = busy;
  document.getElementById("btn-stop").hidden = !busy;
}

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
  try { res = await api.mine(q, { signal: inFlight ? inFlight.signal : undefined }); }
  catch (err) {
    if (err && err.name === "AbortError") return;   // the user pressed Stop
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
  // A timeout is not a result. The server answers it with an empty list and
  // truncated: true, which the generic branch below would render as
  // "0 position(s) (truncated -- raise max results for more)" -- advice that
  // cannot help, about a scan that never finished.
  if (b.note === "timeout") {
    rows = [];
    status.textContent =
      `Timed out after ${budgetSeconds}s. No results yet — narrow the material, `
      + "or drop the count/starts/ends filters.";
    return;
  }
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
  b.fens.forEach((fen, i) => {
    const li = document.createElement("li");
    const idx = document.createElement("span");
    idx.className = "idx";
    idx.textContent = i + 1;
    const text = document.createElement("span");
    text.className = "fen";
    text.textContent = fen;
    li.append(idx, text);
    li.addEventListener("click", () => { location.hash = encodeState({ fen, panel: "explorer" }); });
    results.appendChild(li);
  });
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

  api.health().then(({ body }) => {
    if (typeof body.mine_timeout === "number" && body.mine_timeout > 0)
      budgetSeconds = body.mine_timeout;
  }).catch(() => { /* keep the default; the countdown is a nicety */ });

  document.getElementById("btn-stop").addEventListener("click", () => {
    if (inFlight) inFlight.abort();
    inFlight = null;
    stopTicker();
    setBusy(false);
    mineSeq++;   // retire any scheduled 202 retry
    // Honest about what aborting does and does not do: the scan runs in the
    // server's thread pool and abandoning the response does not free it.
    status.textContent = "Stopped. The server finishes or drops this scan within "
      + `${budgetSeconds}s.`;
  });

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const q = Object.fromEntries(new FormData(form).entries());
    q.theme = selectedThemes(themeSel);      // fromEntries would keep only one
    results.textContent = ""; rows = [];
    const bad = validate(q);
    if (bad) { status.textContent = bad; return; }
    status.textContent = "searching…";
    const seq = ++mineSeq;
    inFlight = new AbortController();
    setBusy(true);
    startTicker(status);
    try {
      await runQuery(q, status, results, seq);
    } finally {
      if (seq === mineSeq) { stopTicker(); setBusy(false); inFlight = null; }
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
