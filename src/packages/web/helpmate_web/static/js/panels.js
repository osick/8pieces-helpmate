import { decodeState, encodeState } from "./lib/state.js";

export function showPanel(name) {
  for (const btn of document.querySelectorAll("nav button"))
    btn.classList.toggle("active", btn.dataset.panel === name);
  for (const id of ["explorer", "puzzles", "materials", "mine", "themes"])
    document.getElementById(`panel-${id}`).hidden = id !== name;
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
