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
  // The WHOLE fen, not a prefix. parseEpd's one transformation is appending
  // the two clock fields EPD does not carry ("0 1"), and every /v1/ endpoint
  // 400s a FEN without them -- a prefix check passed with that append
  // deleted, i.e. with every puzzle in production broken.
  assert.equal(ps[0].fen, "8/7k/5K2/8/8/8/8/6Q1 b - - 0 1");
  assert.equal(ps[1].fen, "7k/8/5K2/8/8/8/8/6Q1 w - - 0 1");
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
  // The floor is the same kind of PROVEN one the test above uses, not a
  // round number: the filtered pool is 50 puzzles at dtm 2, 6, 10, ..., 198,
  // one per rung, so 10 bands of 5 rungs each put band 0 at dtm 2..18 and
  // band 9 at dtm 182..198 -- a span that can never be narrower than
  // 182 - 18 = 164. A threshold below that (90, as this test first shipped)
  // is satisfied by badly broken banding, which is the exact defect the test
  // above was fixed for and this one then repeated.
  assert.ok(s[9].dtm - s[0].dtm >= 164, `span too narrow after filtering: ${s[0].dtm}..${s[9].dtm}`);
});

test("pickSession's default isAvailable (null) changes nothing -- existing call sites are untouched", () => {
  const all = [{ fen: "8/7k/5K2/8/8/8/8/6Q1 b - - 0 1", dtm: 4, id: "only" }];
  assert.deepEqual(pickSession(all, 10, Math.random), pickSession(all, 10, Math.random, null));
});

// Fix round 2: banding used to cut the sorted pool at equal raw INDEX, which
// can slice a single (dtm, pieces) rung across two adjacent bands whenever
// rung sizes are uneven -- which every real mined corpus is, since rung
// size is real availability, not a target. Measured against the real
// puzzles.epd shape (five thousand simulated sessions): 21.95% of adjacent
// transitions collided, and 98.8% of ten-puzzle sessions had at least one --
// not an edge case, nearly every session. Banding is now cut across
// DISTINCT RUNGS instead, so two adjacent bands can never share one.
const REAL_SHAPED_RUNG_SIZES = [100, 100, 100, 100, 100, 100, 100, 100, 90, 40];

function makeUnevenRungPool() {
  const all = [];
  let dtm = 2;
  for (const size of REAL_SHAPED_RUNG_SIZES) {
    for (let k = 0; k < size; k++) {
      all.push({ fen: "8/7k/5K2/8/8/8/8/6Q1 b - - 0 1", dtm, id: `${dtm}-${k}` });
    }
    dtm += 2;
  }
  return all;
}

test("pickSession never puts two adjacent slots on the same rung when there are at least n rungs", () => {
  const all = makeUnevenRungPool();
  let seed = 11;
  const rnd = () => ((seed = (seed * 1103515245 + 12345) % 2147483648) / 2147483648);
  for (let trial = 0; trial < 200; trial++) {
    const s = pickSession(all, 10, rnd);
    for (let i = 1; i < s.length; i++) {
      assert.notEqual(s[i].dtm, s[i - 1].dtm,
        `trial ${trial}: adjacent slots ${i - 1},${i} both landed on dtm ${s[i].dtm} -- ` +
        `full session: ${s.map((p) => p.dtm)}`);
    }
  }
});

test("the equal-INDEX banding this replaced DOES collide on that same pool -- proving the test above has teeth", () => {
  const sorted = [...makeUnevenRungPool()].sort(byDifficulty);
  // pickSession's banding before this fix: cut the sorted array into n
  // equal-width INDEX ranges, oblivious to where a rung's boundary fell.
  function oldIndexBandedPick(sortedPool, n, rnd) {
    const band = sortedPool.length / n;
    const out = [];
    for (let i = 0; i < n; i++) {
      const lo = Math.floor(i * band);
      const hi = Math.max(lo + 1, Math.floor((i + 1) * band));
      out.push(sortedPool[lo + Math.floor(rnd() * (hi - lo))]);
    }
    return out;
  }
  let seed = 1;
  const rnd = () => ((seed = (seed * 1103515245 + 12345) % 2147483648) / 2147483648);
  let collided = false;
  for (let trial = 0; trial < 100 && !collided; trial++) {
    const s = oldIndexBandedPick(sorted, 10, rnd);
    for (let i = 1; i < s.length && !collided; i++) {
      if (s[i].dtm === s[i - 1].dtm) collided = true;
    }
  }
  assert.ok(collided,
    "expected the old index-banding algorithm to collide at least once in 100 sessions on this " +
    "real-shaped pool -- if it never does, the no-collision test above isn't exercising the bug " +
    "it exists to guard against");
});

test("pickSession still returns n puzzles, sorted, without padding, when there are fewer rungs than slots", () => {
  // A thin install: only 3 distinct (dtm, pieces) rungs survive an
  // isAvailable filter, but plenty of puzzles within each. n=10 slots must
  // still total 10 -- some rungs necessarily supply more than one, which is
  // an honest, unavoidable collision here, not a defect -- and the result
  // must stay sorted easiest-first, not just grouped by rung.
  const all = [
    ...Array.from({ length: 20 }, (_, i) => ({
      fen: "8/7k/5K2/8/8/8/8/6Q1 b - - 0 1", dtm: 4, id: `a${i}`,
    })),
    ...Array.from({ length: 20 }, (_, i) => ({
      fen: "8/7k/5K2/8/8/8/8/6Q1 b - - 0 1", dtm: 8, id: `b${i}`,
    })),
    ...Array.from({ length: 20 }, (_, i) => ({
      fen: "8/7k/5K2/8/8/8/8/6Q1 b - - 0 1", dtm: 12, id: `c${i}`,
    })),
  ];
  let seed = 5;
  const rnd = () => ((seed = (seed * 1103515245 + 12345) % 2147483648) / 2147483648);
  const s = pickSession(all, 10, rnd);
  assert.equal(s.length, 10);
  assert.equal(new Set(s.map((p) => p.id)).size, 10, "a puzzle repeated");
  const dtms = s.map((p) => p.dtm);
  assert.deepEqual(dtms, [...dtms].sort((a, b) => a - b), "not ordered easiest first");
  // Every one of the 3 available rungs must appear -- none skipped.
  assert.deepEqual([...new Set(dtms)].sort((a, b) => a - b), [4, 8, 12]);
});
