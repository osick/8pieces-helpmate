import test from "node:test";
import assert from "node:assert/strict";
import { toPgn, toFenList, toCsv } from "../../helpmate_web/static/js/lib/export.js";

const FEN = "8/7k/5K2/8/8/8/8/6Q1 b - - 0 1";

test("PGN carries the position and one movetext per line", () => {
  const pgn = toPgn(FEN, [["Kh6", "Qh2#"], ["Kh8", "Qg7#"]]);
  assert.ok(pgn.includes(`[FEN "${FEN}"]`));
  assert.ok(pgn.includes("[SetUp \"1\"]"));
  // black moves first in a helpmate, so movetext starts with "1..."
  assert.ok(pgn.includes("1... Kh6 2. Qh2#"), pgn);
  assert.equal(pgn.split("[Event").length - 1, 2, "one game per line");
});

test("FEN list is one position per line, newline-terminated", () => {
  assert.equal(toFenList([FEN, FEN]), `${FEN}\n${FEN}\n`);
  assert.equal(toFenList([]), "");
});

test("CSV has a header and quotes the FEN field", () => {
  const csv = toCsv([{ fen: FEN, dtm: 2, count: 4 }]);
  const [head, row] = csv.trim().split("\n");
  assert.equal(head, "fen,dtm,count");
  assert.equal(row, `"${FEN}",2,4`);
});
