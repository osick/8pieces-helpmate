import { api, ApiError, DOWNLOAD_RETRY_CAP, DOWNLOAD_RETRY_MS } from "./api.js";
import { fmtSize, el, renderStats } from "./stats-view.js";

// Monotonic token guarding showStats(): every call captures its own seq at
// entry, and bails out after each await (and inside the 202 retry callback)
// if a newer showStats() has since started -- otherwise a slow, stale poll
// (e.g. the user clicked a different material while a download was still in
// progress) could overwrite #material-stats with the wrong material's data.
let statsSeq = 0;

async function showStats(name, { retries = 0, seq } = {}) {
  if (seq === undefined) seq = ++statsSeq;
  const box = document.getElementById("material-stats");
  const say = (text) => { box.textContent = ""; box.appendChild(el("p", "empty", text)); };
  if (retries === 0) say(`Loading ${name}…`);
  let res;
  try { res = await api.stats(name); }
  catch (err) {
    if (seq !== statsSeq) return;   // superseded by a newer showStats()
    if (err instanceof ApiError) { say(err.hint ? `${err.message} — ${err.hint}` : err.message); return; }
    throw err;
  }
  if (seq !== statsSeq) return;     // superseded by a newer showStats()
  if (res.status === 202) {
    if (retries >= DOWNLOAD_RETRY_CAP) {
      say(`Still downloading ${name} — this is taking longer than expected, re-selecting the material will resume it.`);
      return;
    }
    say(`Downloading ${name}…`);
    setTimeout(() => {
      if (seq !== statsSeq) return; // user navigated away: stop retrying
      showStats(name, { retries: retries + 1, seq });
    }, DOWNLOAD_RETRY_MS);
    return;
  }
  renderStats(box, res.body);
}

export async function initMaterials() {
  const list = document.getElementById("material-list");
  const box = document.getElementById("material-stats");
  box.appendChild(el("p", "empty", "Select a table to see its statistics."));
  list.textContent = "";
  list.appendChild(el("li", "empty", "Loading…"));
  let res;
  try { res = await api.materials(); }
  catch (err) {
    list.textContent = "";
    if (err instanceof ApiError) {
      list.appendChild(el("li", "empty", err.hint ? `${err.message} — ${err.hint}` : err.message));
      window.__materialsReady = true;
      return;
    }
    throw err;
  }
  list.textContent = "";
  if (!res.body.materials.length)
    list.appendChild(el("li", "empty", "No tables yet. Generate one with `helpmate gen KQvk`."));
  for (const m of res.body.materials) {
    const li = el("li");
    li.append(el("span", "name", m.material),
              el("span", "meta", `  ${m.pieces} pieces · ${fmtSize(m.size_bytes)} · ${m.location}`));
    li.dataset.material = m.material;
    li.addEventListener("click", () => {
      for (const other of list.children) other.removeAttribute("aria-selected");
      li.setAttribute("aria-selected", "true");
      showStats(m.material);
    });
    list.appendChild(li);
  }
  window.__materialsReady = true;
}
