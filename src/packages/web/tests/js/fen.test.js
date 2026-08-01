import test from "node:test";
import assert from "node:assert/strict";
import {
  EMPTY_PLACEMENT, splitFen, composeFen, withSideToMove, withPlacement,
  kingProblem, looksLikePlacement,
} from "../../helpmate_web/static/js/lib/fen.js";

const GOLDEN = "8/7k/5K2/8/8/8/8/6Q1 b - - 0 1";

test("splits a full FEN into placement and side to move", () => {
  assert.deepEqual(splitFen(GOLDEN), { placement: "8/7k/5K2/8/8/8/8/6Q1", stm: "b" });
});

test("splitting tolerates a bare placement and defaults to White", () => {
  assert.deepEqual(splitFen("8/8/8/8/8/8/8/8"), { placement: EMPTY_PLACEMENT, stm: "w" });
  assert.equal(splitFen("").placement, EMPTY_PLACEMENT);
  assert.equal(splitFen(null).stm, "w");
});

test("composes the fixed tablebase FEN shape", () => {
  assert.equal(composeFen("8/7k/5K2/8/8/8/8/6Q1", "b"), GOLDEN);
  // no castling rights, no en-passant target -- the generator never has them
  assert.ok(composeFen(EMPTY_PLACEMENT, "w").endsWith(" w - - 0 1"));
});

test("an unrecognised side to move falls back to White rather than corrupting the FEN", () => {
  assert.equal(composeFen(EMPTY_PLACEMENT, "x"), `${EMPTY_PLACEMENT} w - - 0 1`);
});

test("round-trips through the two editing operations", () => {
  assert.equal(withSideToMove(GOLDEN, "w"), "8/7k/5K2/8/8/8/8/6Q1 w - - 0 1");
  assert.equal(withPlacement(GOLDEN, "8/8/8/8/8/8/8/8"), "8/8/8/8/8/8/8/8 b - - 0 1");
  assert.equal(withSideToMove(withSideToMove(GOLDEN, "w"), "b"), GOLDEN);
});

test("names the king mistakes an editor actually makes", () => {
  assert.equal(kingProblem("8/7k/5K2/8/8/8/8/6Q1"), null);
  assert.equal(kingProblem(EMPTY_PLACEMENT), "place both kings");
  assert.equal(kingProblem("8/7k/8/8/8/8/8/8"), "place the white king");
  assert.equal(kingProblem("8/8/5K2/8/8/8/8/8"), "place the black king");
  assert.equal(kingProblem("8/7k/5KK1/8/8/8/8/8"), "only one white king");
  assert.equal(kingProblem("8/6kk/5K2/8/8/8/8/8"), "only one black king");
});

test("a hand-typed non-board is left to the server to diagnose", () => {
  // Otherwise "garbage" reads as "place both kings" and the user never sees
  // the server's real invalid_fen message.
  assert.equal(looksLikePlacement("garbage"), false);
  assert.equal(kingProblem("garbage"), null);
  assert.equal(kingProblem("8/7k/5K2"), null, "too few ranks is not an editor mistake");
  assert.equal(looksLikePlacement("8/7k/5K2/8/8/8/8/6Q1"), true);
  assert.equal(looksLikePlacement(EMPTY_PLACEMENT), true);
});

test("king detection is not fooled by other pieces", () => {
  // a queen and a knight are not kings, and the empty-square digits are not either
  assert.equal(kingProblem("8/7k/5K2/8/8/8/8/6QN"), null);
});
