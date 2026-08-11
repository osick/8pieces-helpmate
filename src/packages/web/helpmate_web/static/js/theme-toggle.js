import {
  THEME_KEY, normalizeMode, nextMode, themeAttr, modeLabel,
} from "./lib/theme-mode.js";

// localStorage throws rather than returning null in some privacy modes and
// under a file:// origin. The toggle must still work for the session then --
// it just won't be remembered.
function readMode() {
  try { return normalizeMode(localStorage.getItem(THEME_KEY)); }
  catch { return "system"; }
}
function writeMode(mode) {
  try { localStorage.setItem(THEME_KEY, mode); }
  catch { /* not remembered; the page still honours the click */ }
}

function apply(mode) {
  const attr = themeAttr(mode);
  if (attr === null) document.documentElement.removeAttribute("data-theme");
  else document.documentElement.setAttribute("data-theme", attr);
  const btn = document.getElementById("theme-toggle");
  btn.textContent = modeLabel(mode);
  btn.dataset.mode = mode;
}

export function initTheme() {
  let mode = readMode();
  apply(mode);
  document.getElementById("theme-toggle").addEventListener("click", () => {
    mode = nextMode(mode);
    writeMode(mode);
    apply(mode);
  });
}
