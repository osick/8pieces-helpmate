import { api, ApiError } from "./api.js";
import { encodeState } from "./lib/state.js";

function fmtSize(n) {
  if (n >= 1e9) return `${(n / 1e9).toFixed(2)} GB`;
  if (n >= 1e6) return `${(n / 1e6).toFixed(1)} MB`;
  if (n >= 1e3) return `${(n / 1e3).toFixed(1)} kB`;
  return `${n} B`;
}

async function showStats(name) {
  const box = document.getElementById("material-stats");
  box.textContent = "loading…";
  let res;
  try { res = await api.stats(name); }
  catch (err) {
    if (err instanceof ApiError) { box.textContent = err.hint ? `${err.message} — ${err.hint}` : err.message; return; }
    throw err;
  }
  if (res.status === 202) { box.textContent = `downloading ${name}…`; setTimeout(() => showStats(name), 1500); return; }
  const s = res.body;
  box.textContent = "";
  const h = document.createElement("h2"); h.textContent = `${s.material} — max_dtm ${s.max_dtm}`;
  box.appendChild(h);
  const samples = document.createElement("ul");
  samples.id = "material-samples";
  for (const fen of (s.deepest || []).concat(s.deepest_unique || [])) {
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
  catch (err) { list.textContent = err.message; return; }
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
