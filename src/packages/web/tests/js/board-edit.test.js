import test from "node:test";
import assert from "node:assert/strict";
import {
  squareFromTarget, exceedsDragThreshold, DRAG_THRESHOLD_PX,
} from "../../helpmate_web/static/js/lib/board-edit.js";

// Plain objects, not a DOM: the walk is deliberately written against
// `dataset` and `parentElement` so it needs neither jsdom nor a browser.
const node = (square, parent = null) => ({
  dataset: square ? { square } : {},
  parentElement: parent,
});

test("a square rect answers with its own square", () => {
  assert.equal(squareFromTarget(node("e4")), "e4");
});

test("a piece dropped on a square finds it by walking up", () => {
  const board = node(null, null);
  const rect = node("a1", board);
  const piece = node(null, rect);
  assert.equal(squareFromTarget(piece), "a1");
});

test("a target outside the board answers null, not a guess", () => {
  assert.equal(squareFromTarget(node(null, node(null, null))), null);
  assert.equal(squareFromTarget(null), null);
});

test("the nearest square wins over an ancestor's", () => {
  assert.equal(squareFromTarget(node("h8", node("a1"))), "h8");
});

test("a small movement is a click, not a drag", () => {
  assert.equal(exceedsDragThreshold({ x: 0, y: 0 }, { x: 1, y: 1 }), false);
  assert.equal(exceedsDragThreshold({ x: 0, y: 0 }, { x: DRAG_THRESHOLD_PX + 1, y: 0 }), true);
  assert.equal(exceedsDragThreshold({ x: 10, y: 10 }, { x: 10, y: 10 - DRAG_THRESHOLD_PX - 1 }), true);
});

test("a movement of exactly the threshold is still a click -- the boundary is strict >", () => {
  assert.equal(exceedsDragThreshold({ x: 0, y: 0 }, { x: DRAG_THRESHOLD_PX, y: 0 }), false);
});
