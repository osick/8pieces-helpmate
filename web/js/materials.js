import { api, ApiError } from "./api.js";
import { encodeState } from "./lib/state.js";

function fmtSize(n) {
  if (n >= 1e9) return `${(n / 1e9).toFixed(2)} GB`;
  if (n >= 1e6) return `${(n / 1e6).toFixed(1)} MB`;
  if (n >= 1e3) return `${(n / 1e3).toFixed(1)} kB`;
  return `${n} B`;
}

// Monotonic token guarding showStats(): every call captures its own seq at
// entry, and bails out after each await (and inside the 202 retry callback)
// if a newer showStats() has since started -- otherwise a slow, stale poll
// (e.g. the user clicked a different material while a download was still in
// progress) could overwrite #material-stats with the wrong material's data.
let statsSeq = 0;
// 202 retry bound: ~60s of polling (40 * 1500ms) before giving up.
const DOWNLOAD_RETRY_CAP = 40;

async function showStats(name, { retries = 0, seq } = {}) {
  if (seq === undefined) seq = ++statsSeq;
  const box = document.getElementById("material-stats");
  if (retries === 0) box.textContent = "loading…";
  let res;
  try { res = await api.stats(name); }
  catch (err) {
    if (seq !== statsSeq) return;   // superseded by a newer showStats()
    if (err instanceof ApiError) { box.textContent = err.hint ? `${err.message} — ${err.hint}` : err.message; return; }
    throw err;
  }
  if (seq !== statsSeq) return;     // superseded by a newer showStats()
  if (res.status === 202) {
    if (retries >= DOWNLOAD_RETRY_CAP) {
      box.textContent = `Still downloading ${name} — this is taking longer than expected, re-selecting the material will resume it.`;
      return;
    }
    box.textContent = `downloading ${name}…`;
    setTimeout(() => {
      if (seq !== statsSeq) return; // user navigated away: stop retrying
      showStats(name, { retries: retries + 1, seq });
    }, 1500);
    return;
  }
  const s = res.body;
  box.textContent = "";
  const h = document.createElement("h2"); h.textContent = `${s.material} — max_dtm ${s.max_dtm}`;
  box.appendChild(h);
  const samples = document.createElement("ul");
  samples.id = "material-samples";
  const seen = new Set();
  for (const fen of (s.deepest || []).concat(s.deepest_unique || [])) {
    if (seen.has(fen)) continue;
    seen.add(fen);
    const li = document.createElement("li");
    li.textContent = fen;
    li.addEventListener("click", () => { location.hash = encodeState({ fen, panel: "explorer" }); });
    samples.appendChild(li);
  }
  box.appendChild(samples);
}

export async function initMaterials() {
  const list = document.getElementById("material-list");
  list.textContent = "loading…";
  let res;
  try { res = await api.materials(); }
  catch (err) {
    if (err instanceof ApiError) { list.textContent = err.hint ? `${err.message} — ${err.hint}` : err.message; return; }
    throw err;
  }
  list.textContent = "";
  for (const m of res.body.materials) {
    const li = document.createElement("li");
    li.textContent = `${m.material}  ${m.pieces} pieces  ${fmtSize(m.size_bytes)}  ${m.location}`;
    li.dataset.material = m.material;
    li.addEventListener("click", () => showStats(m.material));
    list.appendChild(li);
  }
  window.__materialsReady = true;
}
