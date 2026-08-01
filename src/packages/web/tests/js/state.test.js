import test from "node:test";
import assert from "node:assert/strict";
import { encodeState, decodeState } from "../../helpmate_web/static/js/lib/state.js";

const FEN = "8/7k/5K2/8/8/8/8/6Q1 b - - 0 1";

test("round-trips a position through the hash", () => {
  const hash = encodeState({ fen: FEN, panel: "explorer" });
  assert.ok(hash.startsWith("#"));
  assert.deepEqual(decodeState(hash), { fen: FEN, panel: "explorer" });
});

test("encodes spaces and slashes safely", () => {
  const hash = encodeState({ fen: FEN, panel: "explorer" });
  assert.ok(!hash.includes(" "), "raw spaces would break the URL");
});

test("defaults when the hash is empty or unknown", () => {
  assert.deepEqual(decodeState(""), { fen: null, panel: "explorer" });
  assert.deepEqual(decodeState("#"), { fen: null, panel: "explorer" });
  assert.equal(decodeState("#panel=mine").panel, "mine");
});
