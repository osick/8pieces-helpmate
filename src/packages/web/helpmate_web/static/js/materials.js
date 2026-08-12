import { api, ApiError, DOWNLOAD_RETRY_CAP, DOWNLOAD_RETRY_MS } from "./api.js";
import { fmtSize, el, renderStats, renderAggregate } from "./stats-view.js";

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

const ALL = "*";   // the pinned "All tables" entry's data-material

function applyFilter(list, term) {
  const q = term.trim().toLowerCase();
  for (const li of list.children) {
    // "All tables" is never filtered away -- it is the way back to the
    // summary, and hiding it would strand a user who typed a term matching
    // nothing. Group headings go while a filter is active: with the list
    // narrowed to a handful, "4 PIECES" over one row is furniture.
    if (li.dataset.material === ALL) { li.hidden = false; continue; }
    if (li.classList.contains("group")) { li.hidden = Boolean(q); continue; }
    // An empty corpus's list holds a "No tables yet" note, which carries no
    // data-material and is not a group heading. Reading .toLowerCase() off
    // that undefined threw on every keystroke and killed the filter for the
    // whole session -- and an empty corpus is the FIRST thing a new install
    // sees. The note is the entire content of the list there, so it stays
    // put rather than being filtered away to nothing.
    if (!li.dataset.material) continue;
    li.hidden = Boolean(q) && !li.dataset.material.toLowerCase().includes(q);
  }
}

async function showOverall() {
  const seq = ++statsSeq;
  const box = document.getElementById("material-stats");
  box.textContent = "";
  box.appendChild(el("p", "empty", "Summing every table…"));
  try {
    const res = await api.overall();
    if (seq !== statsSeq) return;
    renderAggregate(box, res.body);
  } catch (err) {
    if (seq !== statsSeq) return;
    if (!(err instanceof ApiError)) throw err;
    box.textContent = "";
    box.appendChild(el("p", "empty", err.hint ? `${err.message} — ${err.hint}` : err.message));
  }
}

export async function initMaterials() {
  const list = document.getElementById("material-list");
  const filter = document.getElementById("material-filter");
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

  const select = (li, run) => {
    for (const other of list.children) other.removeAttribute("aria-selected");
    li.setAttribute("aria-selected", "true");
    run();
  };

  list.textContent = "";
  const all = el("li", "all");
  all.dataset.material = ALL;
  all.append(el("span", "name", "All tables"),
             el("span", "meta", `  ${res.body.materials.length} tables`));
  all.addEventListener("click", () => select(all, showOverall));
  list.appendChild(all);

  if (!res.body.materials.length)
    list.appendChild(el("li", "empty", "No tables yet. Generate one with `helpmate gen KQvk`."));

  // Grouped by piece count, in the order the catalog already sorts them.
  let group = null;
  for (const m of [...res.body.materials].sort((a, b) => a.pieces - b.pieces
                                                       || a.material.localeCompare(b.material))) {
    if (m.pieces !== group) {
      group = m.pieces;
      const h = el("li", "group", `${group} pieces`);
      list.appendChild(h);
    }
    const li = el("li");
    li.append(el("span", "name", m.material),
              el("span", "meta", `  ${fmtSize(m.size_bytes)} · ${m.location}`));
    li.dataset.material = m.material;
    li.addEventListener("click", () => select(li, () => showStats(m.material)));
    list.appendChild(li);
  }

  filter.addEventListener("input", () => applyFilter(list, filter.value));

  select(all, showOverall);
  window.__materialsReady = true;
}
