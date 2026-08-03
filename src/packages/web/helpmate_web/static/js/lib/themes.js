// Pure helpers for the theme surfaces. Kept out of mine.js/explorer.js so they
// are testable under `node --test` with no DOM.

// The theme names chosen in a <select multiple>, as a plain array.
export function selectedThemes(el) {
  if (!el || !el.selectedOptions) return [];
  return Array.from(el.selectedOptions, (o) => o.value);
}

// One line of prose for a position's detected themes.
export function themeSummary(names) {
  if (names === undefined || names === null) return "";
  return names.length ? names.join(" · ") : "no themes detected";
}
