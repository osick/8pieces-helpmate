// The puzzle set and how a session is drawn from it. Pure -- no DOM, no
// network -- so `node --test` covers selection and grading without a browser.
//
// The set ships as EPD: one position per line, the chess-standard container
// for position collections. It is hand-editable on purpose, because custom
// problems are meant to be added by typing a line.
//
//   8/7k/5K2/8/8/8/8/6Q1 b - - ; hm 4 ; id "KQvk.0001"
//
// Exactly two opcodes are read: `hm`, the helpmate distance IN PLIES (so
// `hm 4` is h#2), and `id`. Unknown opcodes are ignored, so a future field
// costs nothing. `hm` is stored rather than probed so that ordering a
// thousand puzzles is free; piece count is derived, so it is not stored.

export function parseEpd(text) {
  const out = [];
  for (const raw of String(text || "").split("\n")) {
    const line = raw.trim();
    if (!line || line.startsWith("#")) continue;
    const [head, ...ops] = line.split(";");
    const fields = head.trim().split(/\s+/);
    // placement, side to move, castling, en passant -- EPD has no clocks, so
    // append the two the rest of this app's FEN handling expects.
    if (fields.length < 4) continue;
    const p = { fen: `${fields.slice(0, 4).join(" ")} 0 1`, dtm: null, id: null };
    for (const op of ops) {
      const t = op.trim();
      if (!t) continue;
      const key = t.split(/\s+/)[0];
      const val = t.slice(key.length).trim().replace(/^"|"$/g, "");
      if (key === "hm") p.dtm = Number(val);
      else if (key === "id") p.id = val;
    }
    if (!Number.isFinite(p.dtm) || p.dtm <= 0) continue;
    out.push(p);
  }
  return out;
}

// The material a FEN belongs to, by the SAME rule the server uses to name
// its tables (helpmate_server/app.py's `_dir_for_fen`): white piece letters
// sorted King/Queen/Rook/Bishop/Knight/Pawn, then "v", then black's letters
// the same way, lowercased. Used to filter the puzzle set down to whatever
// materials this installation actually has before pickSession ever sees it
// -- a puzzle whose material nobody has generated is not a harder puzzle,
// it is a 404.
const PIECE_ORDER = "KQRBNP";

export function materialOf(fen) {
  const board = String(fen || "").split(/\s+/)[0] || "";
  const side = (test) => [...board]
    .filter((c) => test(c) && PIECE_ORDER.includes(c.toUpperCase()))
    .map((c) => c.toUpperCase())
    .sort((a, b) => PIECE_ORDER.indexOf(a) - PIECE_ORDER.indexOf(b))
    .join("");
  const white = side((c) => c >= "A" && c <= "Z");
  const black = side((c) => c >= "a" && c <= "z");
  return `${white}v${black.toLowerCase()}`;
}

export function pieceCount(fen) {
  const placement = String(fen || "").split(/\s+/)[0] || "";
  let n = 0;
  for (const c of placement) if (/[pnbrqk]/i.test(c)) n++;
  return n;
}

// Mate length first -- a longer helpmate is harder. Piece count second, at
// equal length. [dtm, pieces] -- a display/inspection tuple, NOT something
// to compare with `<`: JS orders arrays by stringifying them, so
// [6, 5] < [10, 6] is false even though dtm 6 is the easier puzzle (any
// double-digit dtm against a single-digit one breaks this the same way).
// For ordering, always use byDifficulty (below) or compare .dtm/pieceCount
// numerically yourself -- never the array this function returns.
export function difficultyOf(p) {
  return [p.dtm, pieceCount(p.fen)];
}

// The safe, numeric comparator -- pass to Array#sort, never `<` on
// difficultyOf's own return value (see the warning above).
export function byDifficulty(a, b) {
  const [ad, ap] = difficultyOf(a), [bd, bp] = difficultyOf(b);
  return (ad - bd) || (ap - bp);
}

// Consecutive runs of equal difficulty in an already-sorted (by byDifficulty)
// array -- i.e. one group per distinct (dtm, pieces) rung, in ascending
// order. Grouping BY RUNG rather than by raw array index is the whole point
// of the banding fix below: two puzzles that are the same difficulty must
// never be allowed to land in two different bands of a would-be index-based
// split, because index-based bands don't know or care where a rung's
// boundary actually falls.
function groupByRung(sortedPool) {
  const groups = [];
  for (const p of sortedPool) {
    const last = groups[groups.length - 1];
    if (last && byDifficulty(last[0], p) === 0) last.push(p);
    else groups.push([p]);
  }
  return groups;
}

// Splits `total` items into `parts` contiguous index ranges [lo, hi), as
// even as floor/ceil allows, each at least 1 wide (so no band is ever
// empty when total >= parts). Same arithmetic pickSession always used, just
// factored out so it can partition either puzzles-by-index (the old,
// collision-prone use) or, now, rungs-by-index / slots-by-rung.
function bandRanges(total, parts) {
  const ranges = [];
  const width = total / parts;
  for (let i = 0; i < parts; i++) {
    const lo = Math.floor(i * width);
    const hi = Math.max(lo + 1, Math.floor((i + 1) * width));
    ranges.push([lo, hi]);
  }
  return ranges;
}

// n puzzles, easiest first, no repeats, spanning the whole range rather than
// clustering. Bands are cut across DISTINCT DIFFICULTY RUNGS, not raw sorted
// index: cutting by index (the original approach) can slice a single rung
// across two adjacent bands whenever rung sizes are uneven -- which real
// mined corpora always are, since rung size is real availability, not a
// target -- so two neighbouring session slots could and did land on the
// exact same (dtm, pieces) in the vast majority of sessions. Banding by rung
// makes that impossible whenever there are at least n rungs: each band
// covers a disjoint range of rungs, so adjacent slots are drawn from
// disjoint sets of difficulties by construction, not by luck.
//
// When there are FEWER than n distinct rungs -- an availability filter can
// easily cause this, e.g. an install with only two or three materials --
// n puzzles can't come from n different difficulties. The slots are then
// spread across the rungs that exist as evenly as floor/ceil allows (a rung
// smaller than its fair share is topped up from whatever's left, in
// difficulty order, so the session is still exactly n long rather than
// short); adjacent collisions are then unavoidable and left as what they
// are, not padded away.
//
// `isAvailable`, when given, filters the pool BEFORE any of the above -- so
// a session drawn from a thin, partially-generated install still spans
// whatever range survives, rather than being cut against the full (mostly
// unplayable) set and discovering most of it is empty. Defaults to null (no
// filtering, every puzzle considered available), which is why every
// existing call site -- and every test above -- is untouched: a 3rd
// positional `rnd` argument still means exactly what it always did.
export function pickSession(all, n, rnd = Math.random, isAvailable = null) {
  const pool = isAvailable ? (all || []).filter(isAvailable) : (all || []);
  const sorted = [...pool].sort(byDifficulty);
  if (sorted.length <= n) return sorted;

  const rungs = groupByRung(sorted);

  if (rungs.length >= n) {
    // Enough distinct difficulties for one each: partition the RUNGS (never
    // splitting one across two bands) into n bands and draw one puzzle at
    // random from each band's rung(s).
    return bandRanges(rungs.length, n).map(([lo, hi]) => {
      const candidates = rungs.slice(lo, hi).flat();
      return candidates[Math.floor(rnd() * candidates.length)];
    });
  }

  // Fewer rungs than slots: give each rung a fair, floor/ceil-even share of
  // the n slots (in difficulty order, so rung 0 gets the earliest slots),
  // draw that many distinct puzzles from it, and top up any shortfall
  // (a rung smaller than its share) from whatever remains, in difficulty
  // order, so the result is still n long and still sorted.
  const remaining = rungs.map((r) => [...r]);
  const picked = [];
  for (const [r, [lo, hi]] of bandRanges(n, rungs.length).entries()) {
    const want = hi - lo;
    const take = Math.min(want, remaining[r].length);
    for (let k = 0; k < take; k++) {
      picked.push(remaining[r].splice(Math.floor(rnd() * remaining[r].length), 1)[0]);
    }
  }
  const leftover = remaining.flat();
  while (picked.length < n && leftover.length) {
    picked.push(leftover.splice(Math.floor(rnd() * leftover.length), 1)[0]);
  }
  return picked.sort(byDifficulty);
}

export function gradeMove(expectedUci, playedUci) {
  return String(expectedUci) === String(playedUci);
}
