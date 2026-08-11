import { test } from "node:test";
import assert from "node:assert/strict";
import {
  THEME_KEY, THEME_MODES, normalizeMode, nextMode, themeAttr, modeLabel,
} from "../../helpmate_web/static/js/lib/theme-mode.js";

test("three states, in cycle order", () => {
  assert.deepEqual(THEME_MODES, ["system", "light", "dark"]);
  assert.equal(THEME_KEY, "helpmate:theme");
});

test("nextMode cycles and wraps", () => {
  assert.equal(nextMode("system"), "light");
  assert.equal(nextMode("light"), "dark");
  assert.equal(nextMode("dark"), "system");
});

test("anything unrecognised is treated as system", () => {
  // localStorage can hold a value written by an older build, a different
  // app on the same origin, or a user poking at devtools. None of those may
  // stamp a bogus data-theme onto the document.
  for (const junk of [null, undefined, "", "Dark", "auto", "{}", 0])
    assert.equal(normalizeMode(junk), "system");
  assert.equal(nextMode("nonsense"), "light");
});

test("system stamps no attribute at all", () => {
  // This is the whole reason for three states rather than two: with no
  // attribute, prefers-color-scheme decides, and the CSS media query is
  // guarded by :not([data-theme=light]) so an explicit light choice still
  // beats a dark OS.
  assert.equal(themeAttr("system"), null);
  assert.equal(themeAttr("nonsense"), null);
  assert.equal(themeAttr("light"), "light");
  assert.equal(themeAttr("dark"), "dark");
});

test("the label states the current mode, so one button is unambiguous", () => {
  assert.equal(modeLabel("system"), "Theme: system");
  assert.equal(modeLabel("dark"), "Theme: dark");
  assert.equal(modeLabel(null), "Theme: system");
});
