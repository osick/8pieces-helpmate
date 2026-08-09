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

// True for a theme whose detector does not need full solution enumeration
// (needs "position" or "plane" rather than "solutions") -- these still
// answer on positions whose stored solution count has saturated (capped at
// 255), where a Needs::Solutions theme is silently skipped. Driven entirely
// by the `needs` field the server reports, never by name.
export function answersOnSaturated(theme) {
  return !!theme && theme.needs !== "solutions" && theme.needs !== undefined;
}

// Tooltip text for a theme picker option: its own definition, with a note
// appended when it also answers on saturated positions.
export function themeOptionTitle(theme) {
  const doc = (theme && theme.doc) || "";
  return answersOnSaturated(theme)
    ? `${doc} (also answers on positions with saturated solution counts)`
    : doc;
}
