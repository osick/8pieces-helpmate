import test from "node:test";
import assert from "node:assert/strict";
import { parseEpd, pieceCount, difficultyOf, byDifficulty, pickSession, gradeMove, materialOf }
  from "../../helpmate_web/static/js/lib/puzzles.js";

const EPD = `# a comment line is ignored
8/7k/5K2/8/8/8/8/6Q1 b - - ; hm 4 ; id "a"
7k/8/5K2/8/8/8/8/6Q1 w - - ; hm 2 ; id "b"
8/7k/5K2/8/6B1/8/8/6Q1 b - - ; hm 8 ; id "c"
`;

test("EPD parses to fen, ply distance and id, skipping comments", () => {
  const ps = parseEpd(EPD);
  assert.equal(ps.length, 3);
  assert.deepEqual(ps.map((p) => p.id), ["a", "b", "c"]);
  assert.deepEqual(ps.map((p) => p.dtm), [4, 2, 8]);
  assert.ok(ps[0].fen.startsWith("8/7k/5K2"));
});

test("an unknown opcode is ignored, not fatal — future custom fields cost nothing", () => {
  const ps = parseEpd('8/7k/5K2/8/8/8/8/6Q1 b - - ; hm 4 ; id "x" ; c0 "by A.N. Other"\n');
  assert.equal(ps.length, 1);
  assert.equal(ps[0].dtm, 4);
});

test("a malformed line is skipped rather than taking the file down", () => {
  const ps = parseEpd('garbage\n8/7k/5K2/8/8/8/8/6Q1 b - - ; hm 4 ; id "ok"\n');
  assert.deepEqual(ps.map((p) => p.id), ["ok"]);
});

test("piece count counts men, not FEN characters", () => {
  assert.equal(pieceCount("8/7k/5K2/8/8/8/8/6Q1 b - - 0 1"), 3);
  assert.equal(pieceCount("8/7k/5K2/8/6B1/8/8/6Q1 b - - 0 1"), 4);
});

test("difficulty is mate length first, piece count second", () => {
  const a = { fen: "8/7k/5K2/8/8/8/8/6Q1 b - - 0 1", dtm: 6 };    // h#3, 3 men
  const b = { fen: "8/7k/5K2/8/6B1/8/8/6Q1 b - - 0 1", dtm: 6 };  // h#3, 4 men
  const c = { fen: "8/7k/5K2/8/8/8/8/6Q1 b - - 0 1", dtm: 16 };   // h#8, 3 men
  assert.deepEqual(difficultyOf(a), [6, 3]);
  assert.deepEqual(difficultyOf(b), [6, 4]);
  // byDifficulty, not `<` on difficultyOf's own array -- this crosses the
  // single-digit/double-digit dtm boundary (6 vs 16) on purpose: JS array
  // comparison stringifies, so [6, 3] < [16, 3] is FALSE ("16..." sorts
  // before "6..." lexicographically) even though dtm 6 is clearly easier.
  // byDifficulty compares the fields numerically and gets it right.
  assert.equal(String(difficultyOf(a) < difficultyOf(c)), "false",
    "demonstrates why difficultyOf's array must never be compared with <");
  assert.ok(byDifficulty(a, c) < 0, "byDifficulty must still rank a before c");
  const sorted = [c, b, a].sort(byDifficulty);
  assert.deepEqual(sorted, [a, b, c]);
});

test("a session is n puzzles, easiest first, without repetition", () => {
  const all = Array.from({ length: 100 }, (_, i) => ({
    fen: "8/7k/5K2/8/8/8/8/6Q1 b - - 0 1", dtm: 2 + 2 * i, id: String(i),
  }));
  let seed = 1;
  const rnd = () => ((seed = (seed * 1103515245 + 12345) % 2147483648) / 2147483648);
  const s = pickSession(all, 10, rnd);
  assert.equal(s.length, 10);
  assert.equal(new Set(s.map((p) => p.id)).size, 10, "a puzzle repeated");
  const dtms = s.map((p) => p.dtm);
  assert.deepEqual(dtms, [...dtms].sort((a, b) => a - b), "not ordered easiest first");
});

test("a session spans the range rather than clustering at one difficulty", () => {
  const all = Array.from({ length: 100 }, (_, i) => ({
    fen: "8/7k/5K2/8/8/8/8/6Q1 b - - 0 1", dtm: 2 + 2 * i, id: String(i),
  }));
  let seed = 7;
  const rnd = () => ((seed = (seed * 1103515245 + 12345) % 2147483648) / 2147483648);
  const s = pickSession(all, 10, rnd);
  // 100 elements / 10 bands = exactly 10 elements (dtm step 20) per band, so
  // correct banding guarantees band 0 (dtm 2..20) and band 9 (dtm 182..200)
  // never overlap: the span can never be less than 182-20 = 162. A threshold
  // below that (e.g. 100) is trivially satisfied even by broken banding, so
  // it would not have caught banding regressing to something narrower than
  // this file's own proven floor.
  assert.ok(s[9].dtm - s[0].dtm >= 162, `span too narrow: ${s[0].dtm}..${s[9].dtm}`);
});

test("a session never exceeds what the set holds", () => {
  const all = [{ fen: "8/7k/5K2/8/8/8/8/6Q1 b - - 0 1", dtm: 4, id: "only" }];
  assert.equal(pickSession(all, 10, Math.random).length, 1);
});

test("grading compares the move actually played", () => {
  assert.equal(gradeMove("h7h8", "h7h8"), true);
  assert.equal(gradeMove("h7h8", "h7h6"), false);
  assert.equal(gradeMove("e7e8q", "e7e8n"), false, "underpromotion is a different move");
});

test("materialOf names a position the same way the server names its tables", () => {
  assert.equal(materialOf("8/7k/5K2/8/8/8/8/6Q1 b - - 0 1"), "KQvk");
  // White's own letters sort K,Q,R,B,N,P regardless of board order or count.
  assert.equal(materialOf("8/7k/5K2/8/6B1/8/8/6Q1 b - - 0 1"), "KQBvk");
  assert.equal(materialOf("k7/8/8/8/8/8/8/KRBNPQ2 w - - 0 1"), "KQRBNPvk");
});

test("pickSession's isAvailable filters the pool before the band arithmetic", () => {
  const all = Array.from({ length: 100 }, (_, i) => ({
    // Even i: KQvk (available below); odd i: KRvk (not available below).
    fen: i % 2 === 0
      ? "8/7k/5K2/8/8/8/8/6Q1 b - - 0 1"
      : "8/7k/5K2/8/8/8/8/6R1 b - - 0 1",
    dtm: 2 + 2 * i, id: String(i),
  }));
  const isAvailable = (p) => materialOf(p.fen) === "KQvk";
  let seed = 3;
  const rnd = () => ((seed = (seed * 1103515245 + 12345) % 2147483648) / 2147483648);
  const s = pickSession(all, 10, rnd, isAvailable);
  assert.equal(s.length, 10);
  assert.ok(s.every((p) => materialOf(p.fen) === "KQvk"), "an unavailable material slipped through");
  // Still spans the (now halved) range, not clustered near the easiest few.
  assert.ok(s[9].dtm - s[0].dtm > 90, `span too narrow after filtering: ${s[0].dtm}..${s[9].dtm}`);
});

test("pickSession's default isAvailable (null) changes nothing -- existing call sites are untouched", () => {
  const all = [{ fen: "8/7k/5K2/8/8/8/8/6Q1 b - - 0 1", dtm: 4, id: "only" }];
  assert.deepEqual(pickSession(all, 10, Math.random), pickSession(all, 10, Math.random, null));
});
