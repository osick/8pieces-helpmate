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

// n puzzles, easiest first, no repeats, spanning the whole range rather than
// clustering: the sorted set is cut into n equal bands and one is drawn at
// random from each. This adapts to whatever the file holds, so adding custom
// problems -- or a deeper corpus -- needs no tier table to be maintained.
//
// `isAvailable`, when given, filters the pool BEFORE the band arithmetic --
// so a session drawn from a thin, partially-generated install still spans
// whatever range survives, rather than the bands being cut against the
// full (mostly unplayable) set and then discovering most of them are empty.
// Defaults to null (no filtering, every puzzle considered available), which
// is why every existing call site -- and every test above -- is untouched:
// a 3rd positional `rnd` argument still means exactly what it always did.
export function pickSession(all, n, rnd = Math.random, isAvailable = null) {
  const pool = isAvailable ? (all || []).filter(isAvailable) : (all || []);
  const sorted = [...pool].sort(byDifficulty);
  if (sorted.length <= n) return sorted;
  const out = [];
  const band = sorted.length / n;
  for (let i = 0; i < n; i++) {
    const lo = Math.floor(i * band);
    const hi = Math.max(lo + 1, Math.floor((i + 1) * band));
    out.push(sorted[lo + Math.floor(rnd() * (hi - lo))]);
  }
  return out;
}

export function gradeMove(expectedUci, playedUci) {
  return String(expectedUci) === String(playedUci);
}
