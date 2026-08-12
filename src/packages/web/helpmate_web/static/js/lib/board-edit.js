// Drag helpers for the position editor. No DOM APIs and no board -- the walk
// is written against `dataset` and `parentElement` so it is testable with
// plain objects, and so `elementFromPoint` stays the caller's business.
//
// cm-chessboard tags every square rect with data-square
// (vendor/cm-chessboard/view/ChessboardView.js:193), which makes the hit test
// a tree walk rather than geometry -- and so it survives the coordinate
// frame, the board's orientation and any future border type without knowing
// about any of them.

// Below this, a pointer gesture is a click and the palette button must still
// behave like a button. Four CSS pixels is the usual floor for a deliberate
// drag and matches what a shaky hand on a trackpad produces.
export const DRAG_THRESHOLD_PX = 4;

export function squareFromTarget(el) {
  for (let n = el; n; n = n.parentElement) {
    const square = n.dataset && n.dataset.square;
    if (square) return square;
  }
  return null;
}

export function exceedsDragThreshold(from, to) {
  if (!from || !to) return false;
  const dx = to.x - from.x;
  const dy = to.y - from.y;
  return Math.hypot(dx, dy) > DRAG_THRESHOLD_PX;
}
