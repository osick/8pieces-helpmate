import { test } from "node:test";
import assert from "node:assert/strict";
import {
  COUNT_SAT, groupMoves, waysLabel, moveBadge, moveClass,
} from "../../helpmate_web/static/js/lib/moves.js";

// Every fixture below is real /v1/moves output, probed against KQvk on
// 2026-08-11. See the plan's "fixture positions" table.

// 8/7k/5K2/8/8/8/8/6Q1 b -- the landing position, in generator order.
const LANDING = [
  { san: "Kh6", dtm: 1, count: 3, solvable: true, optimal: true, notation: "h#0.5" },
  { san: "Kh8", dtm: 1, count: 1, solvable: true, optimal: true, notation: "h#0.5" },
];

// 8/8/7k/8/8/8/8/KQ6 b -- an optimal child whose count has saturated.
const SATURATED = [
  { san: "Kg5", dtm: 9, count: 255, solvable: true, optimal: true, notation: "h#4.5" },
  { san: "Kh5", dtm: 9, count: 246, solvable: true, optimal: true, notation: "h#4.5" },
  { san: "Kg7", dtm: 11, count: 255, solvable: true, optimal: false, notation: "h#5.5" },
];

// 8/8/8/8/8/8/4k3/K2Q4 b -- one move in each group. Kxd1 reaches Kvk.
const THREE = [
  { san: "Kf2", dtm: 9, count: 255, solvable: true, optimal: false, notation: "h#4.5" },
  { san: "Ke3", dtm: 7, count: 16, solvable: true, optimal: true, notation: "h#3.5" },
  { san: "Kxd1", dtm: null, count: 0, solvable: false, optimal: false, notation: null },
];

test("the optimal group is ordered by ascending child count", () => {
  const [optimal] = groupMoves(LANDING);
  assert.equal(optimal.key, "optimal");
  // Kh8 has one continuation, Kh6 has three: the more forcing move leads.
  // The generator emitted them the other way round.
  assert.deepEqual(optimal.moves.map((m) => m.san), ["Kh8", "Kh6"]);
});

test("groups appear in fixed order, and empty groups are omitted", () => {
  assert.deepEqual(groupMoves(THREE).map((g) => [g.key, g.label]),
                   [["optimal", "Optimal"], ["slower", "Slower"], ["dead", "No mate"]]);
  // The landing position has only optimal moves.
  assert.deepEqual(groupMoves(LANDING).map((g) => g.key), ["optimal"]);
  assert.deepEqual(groupMoves([]), []);
  assert.deepEqual(groupMoves(undefined), []);
});

test("the slower group is ordered by dtm, then count, then san", () => {
  const moves = [
    // Qb1's count (2) is deliberately lower than Kf7's (3), even though Qb1
    // sits at the higher dtm: a comparator that dropped dtm and sorted by
    // count alone would place Qb1 before Kf7, so this is the case that tells
    // the two comparators apart.
    { san: "Qb1", dtm: 4, count: 2, solvable: true, optimal: false, notation: "h#2" },
    { san: "Kf7", dtm: 2, count: 3, solvable: true, optimal: false, notation: "h#1" },
    { san: "Qg5", dtm: 2, count: 1, solvable: true, optimal: false, notation: "h#1" },
    { san: "Qa7", dtm: 2, count: 1, solvable: true, optimal: false, notation: "h#1" },
  ];
  const [slower] = groupMoves(moves);
  // dtm 2 before dtm 4; inside dtm 2, count 1 before count 3; the two count-1
  // moves are separated by san.
  assert.deepEqual(slower.moves.map((m) => m.san), ["Qa7", "Qg5", "Kf7", "Qb1"]);
});

test("dead moves sort by san alone and never reach a numeric comparison", () => {
  // dtm is null for every unsolvable move, so null - null (== 0) alone would
  // not distinguish this comparator from the slower group's -- count also
  // has to disagree with san here, or a comparator that fell through to
  // count (as the slower group's does) would tie exactly the same way
  // bySan does and the mutation would go undetected. Qg8+'s count is lower
  // than Qg6's while its san sorts later, so the two comparators disagree.
  //
  // These counts are fictional: a real unsolvable move always carries
  // count: 0, never 1 or 9. That is exactly why they have to be fictional --
  // on real data every dead move ties at both dtm: null and count: 0, so the
  // slower group's (dtm, count, san) comparator degenerates to bySan and no
  // fixture built from real payloads could ever tell the two apart. This
  // test is guarding the contract ("this group sorts by SAN alone"), not
  // reproducing a payload.
  const moves = [
    { san: "Qg8+", dtm: null, count: 1, solvable: false, optimal: false, notation: null },
    { san: "Qg6", dtm: null, count: 9, solvable: false, optimal: false, notation: null },
  ];
  const [dead] = groupMoves(moves);
  assert.equal(dead.key, "dead");
  assert.deepEqual(dead.moves.map((m) => m.san), ["Qg6", "Qg8+"]);
});

test("groupMoves does not mutate its argument", () => {
  const input = LANDING.map((m) => ({ ...m }));
  const order = input.map((m) => m.san);
  groupMoves(input);
  assert.deepEqual(input.map((m) => m.san), order);
});

test("a saturated count is never rendered as a measurement", () => {
  assert.equal(waysLabel(255), "255+ ways");
  assert.equal(waysLabel(COUNT_SAT), "255+ ways");
  assert.equal(waysLabel(254), "254 ways");
  assert.equal(waysLabel(1), "only reply");
  assert.equal(waysLabel(2), "2 ways");
});

test("badges state a claim, and the optimal group is sorted around them", () => {
  const [optimal, slower] = groupMoves(SATURATED);
  assert.deepEqual(optimal.moves.map(moveBadge),
                   ["h#4.5 · 246 ways", "h#4.5 · 255+ ways"]);
  assert.deepEqual(slower.moves.map(moveBadge), ["h#5.5 · slower"]);
});

test("a slower badge omits the count, a dead badge omits everything", () => {
  const [, slower, dead] = groupMoves(THREE);
  assert.equal(moveBadge(slower.moves[0]), "h#4.5 · slower");
  assert.equal(moveBadge(dead.moves[0]), "no mate");
});

test("moveClass carries the group and marks a sole continuation", () => {
  assert.equal(moveClass(LANDING[1]), "optimal only");   // Kh8, count 1
  assert.equal(moveClass(LANDING[0]), "optimal");        // Kh6, count 3
  assert.equal(moveClass(THREE[0]), "slower");
  assert.equal(moveClass(THREE[2]), "dead");
});
