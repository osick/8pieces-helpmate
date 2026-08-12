// Three-state theme selection, pure so `node --test` covers it. The DOM and
// localStorage live in theme-toggle.js.
//
// Three states, not two, because the viewer's default is "follow the system"
// and that is NOT the same as "light": it means stamp no attribute and let
// prefers-color-scheme decide. app.css guards its dark media query with
// :root:not([data-theme="light"]) so an explicit light choice still beats a
// dark OS, and repeats the dark tokens under :root[data-theme="dark"] so the
// toggle wins in the other direction.

export const THEME_KEY = "helpmate:theme";
export const THEME_MODES = ["system", "light", "dark"];

// Anything unrecognised -- a value from an older build, another app on the
// same origin, a hand-edited devtools entry -- is system. A bogus value must
// never reach the document as a data-theme attribute.
export function normalizeMode(value) {
  return THEME_MODES.includes(value) ? value : "system";
}

export function nextMode(mode) {
  const i = THEME_MODES.indexOf(normalizeMode(mode));
  return THEME_MODES[(i + 1) % THEME_MODES.length];
}

// null means "remove the attribute", which is what makes "system" work.
export function themeAttr(mode) {
  const m = normalizeMode(mode);
  return m === "system" ? null : m;
}

// One button cycling three states is only unambiguous if it says which state
// it is in, so the label carries the mode rather than an icon.
export function modeLabel(mode) {
  return `Theme: ${normalizeMode(mode)}`;
}
