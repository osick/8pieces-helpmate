import { test } from "node:test";
import assert from "node:assert/strict";
import { selectedThemes, themeSummary } from "../../helpmate_web/static/js/lib/themes.js";

test("selectedThemes reads the chosen options off a multi-select", () => {
  const el = {
    selectedOptions: [{ value: "model" }, { value: "mirror" }],
  };
  assert.deepEqual(selectedThemes(el), ["model", "mirror"]);
});

test("selectedThemes returns an empty list for no selection", () => {
  assert.deepEqual(selectedThemes({ selectedOptions: [] }), []);
  assert.deepEqual(selectedThemes(null), []);
});

test("themeSummary lists names, and says so when there are none", () => {
  assert.equal(themeSummary(["model", "mirror"]), "model · mirror");
  assert.equal(themeSummary([]), "no themes detected");
  assert.equal(themeSummary(undefined), "");
});
