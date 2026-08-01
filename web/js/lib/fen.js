// FEN assembly for the board editor. Tablebase positions never carry castling
// rights or an en-passant target -- the generator's own FENs are always
// "<placement> <stm> - - 0 1" -- so composing is a fixed shape, not a merge.

export const EMPTY_PLACEMENT = "8/8/8/8/8/8/8/8";

export function splitFen(fen) {
  // "".split(/\s+/) yields [""], not [], so filter before destructuring --
  // otherwise an empty FEN box would compose " w - - 0 1".
  const [placement = EMPTY_PLACEMENT, stm = "w"] =
    String(fen || "").trim().split(/\s+/).filter(Boolean);
  return { placement, stm: stm === "b" ? "b" : "w" };
}

export function composeFen(placement, stm) {
  return `${placement} ${stm === "b" ? "b" : "w"} - - 0 1`;
}

export function withSideToMove(fen, stm) {
  return composeFen(splitFen(fen).placement, stm);
}

export function withPlacement(fen, placement) {
  return composeFen(placement, splitFen(fen).stm);
}

// Eight ranks of piece letters and gap digits. Deliberately loose about rank
// widths -- this only answers "is this a board at all", and the server is the
// authority on whether it is a legal one.
const PLACEMENT_RE = /^[1-8pnbrqkPNBRQK]+(?:\/[1-8pnbrqkPNBRQK]+){7}$/;

export function looksLikePlacement(placement) {
  return PLACEMENT_RE.test(String(placement || ""));
}

// A position the server will reject is worth catching before the round trip,
// but only for the mistakes an editor actually produces: a missing king, or
// more than one of either. Everything else (adjacent kings, a side already in
// check with the wrong side to move) stays the server's call -- and so does
// anything that is not recognisably a board, because a hand-typed FEN deserves
// the server's real diagnosis, not "place both kings".
export function kingProblem(placement) {
  const board = String(placement || "");
  if (!looksLikePlacement(board)) return null;
  const white = (board.match(/K/g) || []).length;
  const black = (board.match(/k/g) || []).length;
  if (white === 0 && black === 0) return "place both kings";
  if (white === 0) return "place the white king";
  if (black === 0) return "place the black king";
  if (white > 1) return "only one white king";
  if (black > 1) return "only one black king";
  return null;
}
