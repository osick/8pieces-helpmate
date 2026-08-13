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

export function pieceCount(fen) {
  const placement = String(fen || "").split(/\s+/)[0] || "";
  let n = 0;
  for (const c of placement) if (/[pnbrqk]/i.test(c)) n++;
  return n;
}

// Mate length first -- a longer helpmate is harder. Piece count second, at
// equal length. Returned as an array so callers can compare lexicographically.
export function difficultyOf(p) {
  return [p.dtm, pieceCount(p.fen)];
}

function byDifficulty(a, b) {
  const [ad, ap] = difficultyOf(a), [bd, bp] = difficultyOf(b);
  return (ad - bd) || (ap - bp);
}

// n puzzles, easiest first, no repeats, spanning the whole range rather than
// clustering: the sorted set is cut into n equal bands and one is drawn at
// random from each. This adapts to whatever the file holds, so adding custom
// problems -- or a deeper corpus -- needs no tier table to be maintained.
export function pickSession(all, n, rnd = Math.random) {
  const sorted = [...(all || [])].sort(byDifficulty);
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
