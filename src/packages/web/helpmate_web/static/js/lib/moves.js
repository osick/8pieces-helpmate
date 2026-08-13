// Grouping and ordering of the legal-move list. Pure -- no DOM, no network --
// so `node --test` covers the whole feature without a browser, and explorer.js
// stays a renderer that knows nothing about what makes a move good.

// The stored optimal-line count saturates here (COUNT_SAT in
// src/core/chess/types.h). A saturated count means "cannot be enumerated",
// not "there are exactly 255", so it must never be rendered as a plain
// number -- the whole project treats the ceiling as an absence of data.
export const COUNT_SAT = 255;

// Ordering inside a group breaks ties on the SAN by plain code-unit
// comparison, never localeCompare: locale-dependent collation would make the
// rendered order depend on the machine the browser runs on, and these lists
// are asserted element-by-element by the tests.
function bySan(a, b) {
  if (a.san < b.san) return -1;
  if (a.san > b.san) return 1;
  return 0;
}

const GROUPS = [
  {
    key: "optimal",
    label: "Optimal",
    holds: (m) => m.optimal === true,
    // dtm is CONSTANT across this group -- every optimal move leads to a
    // child at dtm = D - 1 -- so mate length cannot order it. The child's
    // solution count can: it says how forcing the move is, which is also the
    // property a composer cares about. So the ordering doubles as the advice.
    order: (a, b) => (a.count - b.count) || bySan(a, b),
    // Never banded: the per-move count is exactly what this group exists to
    // show, so its rows keep their badges.
    band: null,
  },
  {
    key: "slower",
    label: "Slower",
    holds: (m) => m.solvable === true && m.optimal !== true,
    order: (a, b) => (a.dtm - b.dtm) || (a.count - b.count) || bySan(a, b),
    // Within one distance every move's badge would read the same, so the
    // distance becomes the band label and the badge disappears.
    band: (m) => m.notation,
  },
  {
    key: "dead",
    label: "No mate",
    holds: (m) => m.solvable !== true,
    // Every move here has dtm null, so it must never reach a numeric
    // comparator: null - null is 0, which would silently degrade to input
    // order rather than failing loudly.
    order: bySan,
    // Nothing distinguishes one dead move from another: one unlabelled band.
    band: () => null,
  },
];

// Non-empty groups, in fixed order. `filter` copies, so the caller's array is
// never reordered -- the drag-to-play path in explorer.js reads the same
// array and relies on it being untouched.
//
// `bands` is null for a group whose rows carry their own badge, and otherwise
// the group's moves split by band label, IN THE GROUP'S OWN ORDER -- the
// comparator already sorts by distance first, so walking the sorted list and
// starting a new band whenever the label changes yields distance order
// without a second sort.
export function groupMoves(moves) {
  const out = [];
  for (const g of GROUPS) {
    const rows = (moves || []).filter(g.holds).sort(g.order);
    if (!rows.length) continue;
    let bands = null;
    if (g.band) {
      bands = [];
      for (const m of rows) {
        const label = g.band(m);
        const last = bands[bands.length - 1];
        if (last && last.label === label) last.moves.push(m);
        else bands.push({ label, moves: [m] });
      }
    }
    out.push({ key: g.key, label: g.label, moves: rows, bands });
  }
  return out;
}

export function waysLabel(count) {
  if (count >= COUNT_SAT) return `${COUNT_SAT}+ ways`;
  return count === 1 ? "only reply" : `${count} ways`;
}

// A badge earns its place only when it says something the group heading and
// the band label cannot. That is true in exactly one group: the optimal
// moves, whose child solution count differs per move and is the property a
// composer is reading the list for. Slower and dead moves are banded by
// distance, so a per-move badge would repeat the band label N times -- which
// is what made the list 25 rows of identical text.
export function moveBadge(move) {
  if (move.solvable !== true) return null;
  if (move.optimal !== true) return null;
  return waysLabel(move.count);
}

// The row's class. "only" marks a child with a single continuation; it is
// drawn as a ring rather than a colour, so nothing is encoded by hue alone.
export function moveClass(move) {
  if (move.solvable !== true) return "dead";
  if (move.optimal !== true) return "slower";
  return move.count === 1 ? "optimal only" : "optimal";
}
