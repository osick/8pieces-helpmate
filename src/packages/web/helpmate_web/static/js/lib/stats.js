// Shaping of /v1/materials/{name}/stats into rows a chart can draw.
// No DOM, no network -- tested with node --test.

// One row per distance-to-mate value, in ply order. Black-to-move plies are
// even and White-to-move odd (a full-move h#n is 2n plies), so the side is
// derivable from the ply itself and never has to be trusted from the payload.
export function dtmBars(stats) {
  const hist = (stats && stats.dtm_histogram) || {};
  const byDtm = new Map();
  for (const side of ["btm", "wtm"])
    for (const [key, n] of Object.entries(hist[side] || {})) {
      const dtm = Number(key);
      if (!Number.isFinite(dtm)) continue;
      byDtm.set(dtm, (byDtm.get(dtm) || 0) + n);
    }
  const rows = [...byDtm.entries()].sort((a, b) => a[0] - b[0]);
  const max = rows.reduce((m, [, n]) => Math.max(m, n), 0);
  return rows.map(([dtm, positions]) => ({
    dtm,
    positions,
    side: dtm % 2 === 0 ? "btm" : "wtm",
    // h#0.5 is the server's own notation for a White-to-move half move.
    label: `h#${dtm / 2}`,
    share: max ? positions / max : 0,
  }));
}

// Solution-count buckets. Exact counts matter to a composer at the low end
// ("exactly two solutions") and stop mattering above a handful, so the small
// numbers stay individual and the tail is bucketed by octave.
const BUCKETS = [
  { label: "1", lo: 1, hi: 1 },
  { label: "2", lo: 2, hi: 2 },
  { label: "3", lo: 3, hi: 3 },
  { label: "4", lo: 4, hi: 4 },
  { label: "5–8", lo: 5, hi: 8 },
  { label: "9–16", lo: 9, hi: 16 },
  { label: "17–32", lo: 17, hi: 32 },
  { label: "33–64", lo: 33, hi: 64 },
  { label: "65–128", lo: 65, hi: 128 },
  { label: "129–254", lo: 129, hi: 254 },
  // The generator saturates the counter at 255: such a cell means "at least
  // 255 optimal lines", not "exactly 255".
  { label: "255+", lo: 255, hi: Infinity },
];

export function uniquenessBuckets(stats) {
  const uniq = (stats && stats.uniqueness) || {};
  const totals = BUCKETS.map(() => 0);
  for (const side of ["btm", "wtm"])
    for (const perDtm of Object.values(uniq[side] || {}))
      for (const [key, n] of Object.entries(perDtm || {})) {
        const count = Number(key);
        if (!Number.isFinite(count)) continue;
        const i = BUCKETS.findIndex((b) => count >= b.lo && count <= b.hi);
        if (i >= 0) totals[i] += n;
      }
  // Trim only the empty head and tail: an empty bucket between two occupied
  // ones is real information and must stay visible.
  let first = totals.findIndex((n) => n > 0);
  if (first === -1) return [];
  let last = totals.length - 1;
  while (totals[last] === 0) last--;
  const slice = totals.slice(first, last + 1);
  const max = Math.max(...slice);
  return slice.map((positions, i) => ({
    label: BUCKETS[first + i].label,
    positions,
    share: max ? positions / max : 0,
  }));
}

// Where the cells of a material went. `plane_size` counts one side to move,
// and every cell exists for both, so the total is twice the plane.
export function cellSummary(stats) {
  const cells = (stats && stats.cells) || {};
  const sum = (kind) => {
    const c = cells[kind] || {};
    return (c.btm || 0) + (c.wtm || 0);
  };
  const total = ((stats && stats.plane_size) || 0) * 2;
  const invalid = sum("invalid");
  const unsolvable = sum("unsolvable");
  return { total, invalid, unsolvable, solvable: total - invalid - unsolvable };
}

export function fmtCount(n) {
  return Number(n).toLocaleString("en-US");
}

// A material where nothing is solvable (KBvk: king and bishop cannot mate)
// stores the DTM_UNSOLVABLE sentinel as max_dtm, not a distance, and an empty
// histogram. Dividing it by two yields "h#127.5" -- a measurement-shaped
// string for a measurement that does not exist. 67 of the 295 tables in the
// reference corpus are in this state, so it is the common case, not an edge.
export const DTM_UNSOLVABLE = 255;

export function hasHelpmate(stats) {
  if (!stats) return false;
  if (Number(stats.max_dtm) >= DTM_UNSOLVABLE) return false;
  const hist = stats.dtm_histogram || {};
  return ["btm", "wtm"].some((side) => Object.keys(hist[side] || {}).length > 0);
}

export function mateLengthLabel(stats) {
  if (!hasHelpmate(stats)) return "no helpmate exists in this material";
  return `longest mate h#${Number(stats.max_dtm) / 2}`;
}
