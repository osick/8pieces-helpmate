// The motif documentation screen: what each motif the tablebase's theme
// detector knows means, and what it needs to answer.
//
// Rendered straight from /v1/themes -- never a hardcoded list -- so this
// screen cannot drift from the binary it is talking to. That endpoint is
// the core registry serialised verbatim (see helpmate_server/app.py's
// /v1/themes handler and pymodule.cpp's `themes()` binding): every entry
// carries {name, doc, needs}.
import { api, ApiError } from "./api.js";
import { el } from "./stats-view.js";

// Fixed groups, each introduced by a sentence before its members. A name the
// API returns that is not listed in any group here falls into the trailing
// "other" group instead of being dropped -- see renderThemes() below, which
// never special-cases an unrecognised name, only ones it recognises. That is
// what lets a future motif appear on this screen with no edit to this file.
const GROUPS = [
  {
    title: "The mate picture",
    intro: "What the mating position itself looks like, judged by the "
         + "black king's field.",
    members: ["pure", "model", "ideal", "mirror"],
  },
  {
    title: "The move sequence",
    intro: "What happens along the way to the mate, not just at it.",
    members: ["switchback", "closed-walk", "excelsior", "promotion", "underpromotion"],
  },
  {
    title: "The position's structure",
    intro: "What shape the position or its solution set has, independent "
         + "of the mate picture or the moves that reach it.",
    members: ["set-play", "single-piece"],
  },
];

const OTHER_TITLE = "Other";
const OTHER_INTRO = "Motifs this build detects that do not belong to one of "
  + "the groups above.";

// A one-line explanation of what a `needs` value means for a saturated
// position -- the stored solution count caps at 255, and only a
// Needs::Solutions detector (needs === "solutions") is silently skipped on
// one, because it has to walk the full solution set to answer.
function needsExplanation(needs) {
  if (needs === "solutions")
    return "reads the full solution set, so it is silently skipped on a "
         + "position whose stored solution count has saturated at 255.";
  if (needs === "plane")
    return "reads only the mating position's geometry (the king's field), "
         + "so it still answers even when the solution count has saturated "
         + "at 255.";
  if (needs === "position")
    return "reads the position alone, so it still answers even when the "
         + "solution count has saturated at 255.";
  // Defensive: a `needs` value this screen does not recognise still gets an
  // entry, just without a caveat this file cannot honestly write.
  return "";
}

// One motif's entry: name, definition, and what it needs to answer, with
// any colour-labelled variants (e.g. excelsior:white) nested inside rather
// than listed as their own top-level entries.
function renderEntry(theme, variants) {
  const entry = el("article", "theme-entry");
  entry.dataset.theme = theme.name;
  entry.appendChild(el("h3", null, theme.name));
  entry.appendChild(el("p", "theme-def", theme.doc));
  const expl = needsExplanation(theme.needs);
  entry.appendChild(el("p", "theme-needs",
    expl ? `needs: ${theme.needs} — ${expl}` : `needs: ${theme.needs}`));
  if (variants && variants.length) {
    const box = el("div", "theme-variants");
    for (const v of variants) box.appendChild(renderEntry(v));
    entry.appendChild(box);
  }
  return entry;
}

// Splits the API's flat theme list into the fixed groups plus "other", with
// colour variants (a name containing ":") attached to their base motif's
// entry when that base is itself present, and rendered where the API put
// them (i.e. under "other" too) when it is not.
function renderThemes(container, themes) {
  const byName = new Map(themes.map((t) => [t.name, t]));
  const placed = new Set();

  const variantsOf = (baseName) => themes.filter((t) => {
    const i = t.name.indexOf(":");
    return i !== -1 && t.name.slice(0, i) === baseName && byName.has(baseName);
  });

  const renderGroup = (title, intro, memberNames) => {
    const names = memberNames.filter((n) => byName.has(n) && !placed.has(n));
    if (!names.length) return;
    const section = el("section", "theme-group");
    section.appendChild(el("h2", null, title));
    section.appendChild(el("p", "theme-group-intro", intro));
    for (const name of names) {
      const variants = variantsOf(name);
      section.appendChild(renderEntry(byName.get(name), variants));
      placed.add(name);
      for (const v of variants) placed.add(v.name);
    }
    container.appendChild(section);
  };

  for (const g of GROUPS) renderGroup(g.title, g.intro, g.members);

  // Everything left over, in the order the API returned it: unknown base
  // motifs, and any colour variant whose base was not itself in the API (so
  // it was never attached to anything above).
  const leftover = themes.filter((t) => !placed.has(t.name)).map((t) => t.name);
  renderGroup(OTHER_TITLE, OTHER_INTRO, leftover);
}

export async function initThemesDoc() {
  const box = document.getElementById("themes-doc");
  box.textContent = "";
  box.appendChild(el("p", "help", "Loading motifs…"));

  let body;
  try {
    ({ body } = await api.themes());
  } catch (err) {
    // index.html runs every init*() unguarded in one sequence -- a throw
    // here would take every other screen down with it, so a failed fetch
    // degrades to a message instead.
    box.textContent = "";
    box.appendChild(el("p", "empty",
      err instanceof ApiError
        ? (err.hint ? `${err.message} — ${err.hint}` : err.message)
        : "Could not load the motif list."));
    window.__themesDocReady = true;
    return;
  }

  box.textContent = "";
  box.appendChild(el("p", "help",
    "Every motif this build's tablebase detects, straight from /v1/themes "
  + "-- the same registry the binary itself uses, so nothing here can name "
  + "a motif the build does not actually know."));
  renderThemes(box, body.themes);
  window.__themesDocReady = true;
}
