import { test } from "node:test";
import assert from "node:assert/strict";
import {
  selectedThemes,
  themeSummary,
  answersOnSaturated,
  themeOptionTitle,
} from "../../helpmate_web/static/js/lib/themes.js";

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

// Task 10: the multi-select marks themes that still answer on positions
// whose stored solution count saturates -- driven entirely by `needs`,
// never by name.
test("answersOnSaturated is true for position/plane themes, false for solutions themes", () => {
  assert.equal(answersOnSaturated({ needs: "position" }), true);
  assert.equal(answersOnSaturated({ needs: "plane" }), true);
  assert.equal(answersOnSaturated({ needs: "solutions" }), false);
  assert.equal(answersOnSaturated({}), false);
  assert.equal(answersOnSaturated(null), false);
});

test("themeOptionTitle appends the saturation note only for non-solutions themes", () => {
  assert.equal(themeOptionTitle({ doc: "a mirror-symmetric mate.", needs: "solutions" }),
               "a mirror-symmetric mate.");
  const t = themeOptionTitle({ doc: "reads only the starting position.", needs: "position" });
  assert.equal(t, "reads only the starting position. (also answers on positions with "
                   + "saturated solution counts)");
});
