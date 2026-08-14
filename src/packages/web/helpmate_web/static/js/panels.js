import { decodeState, encodeState } from "./lib/state.js";

// Which panel is on screen. Tracked here rather than read back off the DOM
// so whenPanelShown() below can answer "is this one already active?" before
// its caller has had a chance to register.
let activePanel = null;

// One-shot activation hooks, keyed by panel name.
//
// A screen whose FIRST PAINT costs a network round trip must not pay for it
// while it is hidden. Two concrete failures this exists to prevent, both on
// the configurations a public release actually ships into:
//
//   * the puzzle screen's startSession() -> loadPuzzle() -> /v1/moves. On an
//     install with a remote table chain that call answers 202 and STARTS A
//     DOWNLOAD, which the screen then polls for up to a minute -- for a panel
//     nobody has opened.
//   * the explorer's probe of its landing position. On an install with no
//     tables that answers 404, and #error-banner lives outside <main>, so a
//     `#panel=puzzles` or `#panel=themes` deep link painted a red "no table
//     for material 'KQvk'" over a screen the user never asked for.
//
// Registering here instead means the work happens on the first activation of
// the owning panel -- immediately, if that panel is already the active one
// (a deep link, or the explorer's default), which is why initPanels() runs
// before the init*() functions in index.html.
const pending = new Map();   // panel name -> [fn, ...]; the entry is dropped once fired

export function whenPanelShown(name, fn) {
  if (activePanel === name) { fn(); return; }
  const fns = pending.get(name);
  if (fns) fns.push(fn);
  else pending.set(name, [fn]);
}

// Derived from the document, never hardcoded: a server with search disabled
// removes #panel-mine and its nav button before initPanels() runs, and a
// hardcoded "mine" would make getElementById return null here and throw --
// taking showPanel, the nav and every other screen down with it.
function panelIds() {
  return [...document.querySelectorAll("section[id^='panel-']")]
    .map((s) => s.id.slice("panel-".length));
}

export function showPanel(name) {
  const ids = panelIds();
  // A bookmarked #panel=mine must land somewhere real rather than hiding
  // every section and painting a blank page.
  if (!ids.includes(name)) name = "explorer";
  activePanel = name;
  for (const btn of document.querySelectorAll("nav button"))
    btn.classList.toggle("active", btn.dataset.panel === name);
  for (const id of ids)
    document.getElementById(`panel-${id}`).hidden = id !== name;
  const fns = pending.get(name);
  if (!fns) return;
  pending.delete(name);   // one shot: revisiting a panel must not re-run its init
  for (const fn of fns) fn();
}

export function initPanels() {
  for (const btn of document.querySelectorAll("nav button"))
    btn.addEventListener("click", () => {
      const name = btn.dataset.panel;
      const { fen } = decodeState(location.hash);
      location.hash = encodeState({ fen, panel: name });
      showPanel(name);
    });
  showPanel(decodeState(location.hash).panel);
  window.addEventListener("hashchange", () => showPanel(decodeState(location.hash).panel));
}
