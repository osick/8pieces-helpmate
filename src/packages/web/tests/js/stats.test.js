import test from "node:test";
import assert from "node:assert/strict";
import {
  dtmBars, uniquenessBuckets, cellSummary, fmtCount,
  DTM_UNSOLVABLE, hasHelpmate, mateLengthLabel,
} from "../../helpmate_web/static/js/lib/stats.js";

// Shape of a real /v1/materials/{name}/stats payload, trimmed.
const STATS = {
  material: "KBBvk",
  plane_size: 100,
  max_dtm: 4,
  // 200 cells in total (both planes): 22 invalid + 68 unsolvable + 110 solvable,
  // and the 110 is exactly what the dtm histogram below accounts for.
  cells: { invalid: { btm: 10, wtm: 12 }, unsolvable: { btm: 35, wtm: 33 } },
  dtm_histogram: { btm: { 0: 2, 2: 40, 4: 8 }, wtm: { 1: 5, 3: 55 } },
  uniqueness: {
    btm: { 0: { 1: 2 }, 2: { 1: 30, 2: 6, 7: 4 }, 4: { 255: 8 } },
    wtm: { 1: { 1: 5 }, 3: { 3: 55 } },
  },
};

test("dtm bars are ordered by ply and labelled in h# notation", () => {
  const bars = dtmBars(STATS);
  assert.deepEqual(bars.map((b) => b.dtm), [0, 1, 2, 3, 4]);
  assert.deepEqual(bars.map((b) => b.label), ["h#0", "h#0.5", "h#1", "h#1.5", "h#2"]);
});

test("dtm bars derive the side to move from the ply's parity", () => {
  const bars = dtmBars(STATS);
  assert.deepEqual(bars.map((b) => b.side), ["btm", "wtm", "btm", "wtm", "btm"]);
});

test("dtm bar shares are relative to the tallest bar", () => {
  const bars = dtmBars(STATS);
  const tallest = bars.find((b) => b.dtm === 3);
  assert.equal(tallest.positions, 55);
  assert.equal(tallest.share, 1);
  assert.equal(bars.find((b) => b.dtm === 2).share, 40 / 55);
});

test("dtm bars survive an empty histogram", () => {
  assert.deepEqual(dtmBars({}), []);
  assert.deepEqual(dtmBars({ dtm_histogram: { btm: {}, wtm: {} } }), []);
});

test("uniqueness buckets keep small counts exact and bucket the tail", () => {
  const b = uniquenessBuckets(STATS);
  const byLabel = Object.fromEntries(b.map((x) => [x.label, x.positions]));
  assert.equal(byLabel["1"], 2 + 30 + 5);   // both sides, all dtm values
  assert.equal(byLabel["2"], 6);
  assert.equal(byLabel["3"], 55);
  assert.equal(byLabel["5–8"], 4);          // the count-7 cells
  assert.equal(byLabel["255+"], 8);         // saturated
});

test("uniqueness keeps interior gaps but trims the empty head and tail", () => {
  const b = uniquenessBuckets(STATS);
  assert.equal(b[0].label, "1", "leading empty buckets would be noise");
  assert.equal(b[b.length - 1].label, "255+");
  assert.ok(b.some((x) => x.positions === 0), "the gap between 3 and 5–8 must stay visible");
});

test("uniqueness returns nothing when there is nothing solvable", () => {
  assert.deepEqual(uniquenessBuckets({ uniqueness: { btm: {}, wtm: {} } }), []);
});

test("cell summary accounts for both planes and derives solvable", () => {
  const s = cellSummary(STATS);
  assert.equal(s.total, 200);
  assert.equal(s.invalid, 22);
  assert.equal(s.unsolvable, 68);
  assert.equal(s.solvable, 110);
  // and it agrees with the dtm histogram, which is the same set of cells
  const fromHist = dtmBars(STATS).reduce((n, b) => n + b.positions, 0);
  assert.equal(s.solvable, fromHist);
});

test("counts are grouped for reading", () => {
  assert.equal(fmtCount(1892352), "1,892,352");
  assert.equal(fmtCount(0), "0");
});

test("a material with no helpmate is named, not divided", () => {
  // KBvk: king and bishop cannot mate. The generator stores the
  // DTM_UNSOLVABLE sentinel as max_dtm and an empty histogram.
  const kbvk = { material: "KBvk", max_dtm: 255, dtm_histogram: { btm: {}, wtm: {} } };
  assert.equal(hasHelpmate(kbvk), false);
  assert.equal(mateLengthLabel(kbvk), "no helpmate exists in this material");
  assert.ok(!mateLengthLabel(kbvk).includes("127.5"));
});

test("a material with a helpmate reports it in h# notation", () => {
  const kqvk = { material: "KQvk", max_dtm: 2, dtm_histogram: { btm: { "2": 9 }, wtm: {} } };
  assert.equal(hasHelpmate(kqvk), true);
  assert.equal(mateLengthLabel(kqvk), "longest mate h#1");
});

test("an odd max_dtm keeps the half step", () => {
  const s = { max_dtm: 33, dtm_histogram: { btm: {}, wtm: { "33": 4 } } };
  assert.equal(mateLengthLabel(s), "longest mate h#16.5");
});

test("the sentinel is recognised even if a histogram is present", () => {
  // Belt and braces: max_dtm is the sentinel and must win regardless.
  const s = { max_dtm: DTM_UNSOLVABLE, dtm_histogram: { btm: { "4": 1 }, wtm: {} } };
  assert.equal(mateLengthLabel(s), "no helpmate exists in this material");
});
