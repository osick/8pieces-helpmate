# Puzzles, Theme Documentation and a Lighter Shell — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the blocking findings from v0.12.0's whole-branch review, delete the colour-theme machinery, stop the page jumping, and add two screens the corpus has earned — a puzzle trainer and documentation for the twelve chess motifs.

**Architecture:** No new API endpoints and no build step. Puzzles ship as a hand-editable **EPD** file mined offline; the tablebase grades them through the existing `/v1/line` and `/v1/moves`. Session selection and grading are pure functions in `js/lib/`, node-tested without a browser. The theme screen renders from `/v1/themes`, so it cannot drift from the binary.

**Tech Stack:** Vanilla ES modules from site-packages, cm-chessboard 8.7.5 (vendored), FastAPI, pytest, Playwright, `node --test`.

**Spec:** `docs/superpowers/specs/2026-08-13-puzzles-and-polish-design.md`

## Global Constraints

- **Every build/test command under `taskset -c 0-3`.** Never more cores.
- **Never write to `~/tb` or `~/tb/raw`** — a generation run is live there. Reading is fine and Task 4 requires it.
- **Never `rm -rf /tmp/tmp.*`** (shared temp dir).
- Prefix pip/build commands with `GIT_CONFIG_GLOBAL=/dev/null`.
- **"Theme" is overloaded in this repo.** A *chess motif* (`set-play`, `mirror`) is what Task 6 documents. The *colour theme* is what Task 2 deletes. Never let one sentence mean both.
- **No new colours.** `tests/repo/test_accent_confined_to_focus_and_hover.py` requires every `var(--accent` inside a `:focus-visible` or `:hover` selector.
- `js/lib/` is the pure node-tested layer: **no DOM APIs, no network**.
- `#move-list li` must select exactly the legal-move entries.
- `position: sticky` stays on `.board-pin`, never `.board-col`.
- **Run every command in the FOREGROUND.** Three agents on the previous plan deadlocked polling background runs, one on a `pgrep` matching its own command line. If you must match a process, bracket it: `pgrep -f "pytes[t] …"`.
- **If you mutate a source file to prove a point, restore it and confirm `git status` is clean before reporting.** A reviewer on the previous plan left a mutation behind that nearly reverted a whole task.
- **Never claim a visual result you have not measured or looked at.**
- Use a **task-specific filename** for scratch scripts — a generic one was silently overwritten by a concurrent agent.
- Commit trailer, exactly: `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`

## File Structure

**Create**

| File | Responsibility |
|---|---|
| `static/puzzles.epd` | The shipped puzzle set. One EPD line per position, hand-editable. |
| `static/js/lib/puzzles.js` | Pure: EPD parsing, piece count, difficulty ordering, session selection, grading. |
| `static/js/puzzle.js` | The puzzle screen's DOM and board wiring. |
| `static/js/themes-doc.js` | Renders the motif documentation from `/v1/themes`. |
| `tools/mine_puzzles.py` | Offline miner that writes `puzzles.epd`. Run by hand, output committed. |
| `tests/js/puzzles.test.js` | node tests for the pure layer. |

**Modify** — `static/index.html` (two new panels, footer, header, no colour-theme control), `static/css/app.css` (dark blocks out, puzzle and themes screens in), `static/js/explorer.js` (atomic swap, `lastMoves` fix), `static/js/panels.js` (two new panels), `static/js/api.js` (`api.puzzles()`), the UI tests, docs and version sites.

**Delete** — `static/js/theme-toggle.js`, `static/js/lib/theme-mode.js`, `tests/js/theme-mode.test.js`, `tests/repo/test_theme_key_not_duplicated_silently.py`.

---

### Task 1: Close the v0.12.0 review's blocking findings

The whole-branch review returned **merge after fixing H1 and M6**, and overturned one of my own rulings (M5). Do all three here; nothing else in this plan should land first.

**Files:**
- Modify: `src/packages/web/helpmate_web/static/js/explorer.js`
- Modify: `docs/USAGE.md`
- Test: `src/packages/web/tests/ui/test_dashboard.py`

- [ ] **Step 1: Write the failing test for H1**

H1: an `ApiError` leaves `lastMoves` stale, so the next drag replays the *previous* position's move list — silently discarding what the user built and printing a confident verdict for a position they never made. Reproduced by the reviewer in two ordinary drags.

```python
def test_a_failed_evaluation_clears_the_move_lookup(page, server):
    # H1 from the v0.12.0 whole-branch review. render()'s kingProblem branch
    # clears lastMoves; the ApiError branch did not. A drag after a failed
    # evaluation then matched against the PREVIOUS position's moves and
    # navigated to that move's child -- discarding the user's edit and
    # rewriting the URL to a position they never built.
    page.goto(server)
    page.wait_for_selector("#move-list li")
    # Put the kings adjacent: legal to build, impossible to probe.
    _drag_square_to_square(page, "f6", "g6")
    page.wait_for_selector("#error-banner:not([hidden])")
    assert page.eval_on_selector_all("#move-list li", "e => e.length") == 0
    broken = page.input_value("#fen-input")
    # This drag corresponds to a move that was legal in the PREVIOUS position.
    _drag_square_to_square(page, "h7", "h8")
    page.wait_for_timeout(400)
    assert page.input_value("#fen-input") != "8/7k/5K2/8/8/8/8/6Q1 b - - 0 1", \
        "the board jumped back to a stale position"
    assert "5K2" not in page.input_value("#fen-input"), \
        "the white king reappeared on f6 -- the stale move list was replayed"
```

- [ ] **Step 2: Run it and watch it fail**

Run: `taskset -c 0-3 make test-web`
Expected: FAIL — the FEN reverts to the pre-edit position.

- [ ] **Step 3: Fix H1**

In `explorer.js`, the `ApiError` branch of `render()` must clear the move lookup exactly as the `kingProblem` branch twelve lines above does:

```js
    if (err instanceof ApiError) {
      showError(err);
      summary.textContent = "";
      // The board must never match a drag against a move list belonging to a
      // position that is no longer on screen: doing so navigates to that
      // move's child, silently discarding whatever the user just built.
      lastMoves = [];
      return;
    }
```

- [ ] **Step 4: Fix M6 — a doc sentence that states the opposite of what shipped**

`docs/USAGE.md` still says the board "is not probed on every drop — a half-built position is illegal by definition, and an error banner per placed piece would be noise". Every drop now evaluates; that is the headline change of v0.12.0. Rewrite the sentence to describe the real behaviour **and its consequence**: building a position piece by piece can raise a banner on intermediate steps, because an intermediate material may have no table.

The same stale claim survives in code at `explorer.js`'s `syncControls` comment, which describes "the editor, which deliberately does not probe on every placement" — a second caller that no longer exists. Correct it too.

- [ ] **Step 5: Fix M5 — my sticky ruling was wrong; add the test that is actually writable**

I ruled that sticky had become moot because "rail and readout are the same height on every position". That measured the wrong quantity: grid `stretch` makes those *always* equal. The quantity that matters is `.board-col` height minus `.board-pin` height, and the reviewer measured real travel:

```
900px  landing (2 moves)        slack 101.7px
900px  THREE_GROUPS (28 moves)  slack  32.0px
900px  KQQQvk (55 moves)        slack 423.2px
```

Chips collapsed only the Slower and No-mate groups; the Optimal group still renders rows, so a many-optimal position still overflows. **Keep sticky.** Add the behavioural test the fixture does support, at 900px on the landing position:

```python
def test_the_board_actually_sticks_when_the_page_scrolls(page, server):
    # M5. The earlier structural-only checks passed even with `top` removed,
    # which disables sticky entirely. At 900px the landing position leaves
    # ~100px of travel between .board-col and .board-pin, so this can assert
    # the real behaviour rather than the CSS declaration.
    page.set_viewport_size({"width": 900, "height": 700})
    page.goto(server)
    page.wait_for_selector("#move-list li")
    before = page.eval_on_selector(".board-pin", "e => e.getBoundingClientRect().top")
    page.evaluate("window.scrollBy(0, 100)")
    page.wait_for_timeout(120)
    after = page.eval_on_selector(".board-pin", "e => e.getBoundingClientRect().top")
    assert after > before - 90, f"the pin scrolled away ({before:.0f} -> {after:.0f}); sticky is inert"
```

**Prove it bites** by adding `top: auto !important` to `.board-pin` — the mutation the old tests were blind to — watching it fail, then restoring.

- [ ] **Step 6: Run the gates and commit**

```bash
taskset -c 0-3 make lint && taskset -c 0-3 make test-web
git add src/packages/web/helpmate_web/static/js/explorer.js docs/USAGE.md \
        src/packages/web/tests/ui/test_dashboard.py
git commit -m "fix(web): clear the move lookup when an evaluation fails

H1 from the v0.12.0 whole-branch review. render()'s kingProblem branch
cleared lastMoves; the ApiError branch did not, so a drag after a failed
evaluation matched against the previous position's move list and
navigated to that move's child -- discarding the user's edit, rewriting
the URL, and printing a confident verdict for a position they never
built. Reachable in two ordinary drags.

Also corrects a USAGE sentence and a code comment that both claimed the
board is not probed on every drop, which is the opposite of what 0.12.0
shipped, and adds the sticky test that M5 showed was writable after all:
the landing position at 900px leaves ~100px of travel, and the previous
structural check passed even with `top` removed.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: One palette, a real title, a footer, a lighter drag ghost

**Files:**
- Delete: `static/js/theme-toggle.js`, `static/js/lib/theme-mode.js`, `tests/js/theme-mode.test.js`, `tests/repo/test_theme_key_not_duplicated_silently.py`
- Modify: `static/index.html`, `static/css/app.css`, `tests/ui/test_dashboard.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_there_is_no_colour_theme_control_and_no_theme_attribute(page, server):
    page.goto(server)
    page.wait_for_selector("#move-list li")
    assert page.eval_on_selector_all("#theme-toggle", "e => e.length") == 0
    assert page.evaluate("document.documentElement.getAttribute('data-theme')") is None


def test_the_title_is_the_most_prominent_text_in_the_header(page, server):
    page.goto(server)
    page.wait_for_selector("#move-list li")
    title = page.eval_on_selector("header h1", "e => parseFloat(getComputedStyle(e).fontSize)")
    tagline = page.eval_on_selector(".tagline", "e => parseFloat(getComputedStyle(e).fontSize)")
    nav = page.eval_on_selector("nav button", "e => parseFloat(getComputedStyle(e).fontSize)")
    assert title >= tagline * 1.6, f"title {title}px vs tagline {tagline}px"
    assert title > nav, f"title {title}px vs nav {nav}px"


def test_the_footer_renders_with_marked_placeholders(page, server):
    page.goto(server)
    page.wait_for_selector("footer")
    assert page.is_visible("footer")
    # Placeholder links are marked so none ships as a live-looking dead link.
    holders = page.eval_on_selector_all("footer a[data-placeholder]", "e => e.length")
    assert holders >= 3, f"only {holders} marked placeholders"


def test_the_drag_ghost_has_no_background_and_is_smaller_than_the_tray(page, server):
    page.goto(server)
    page.wait_for_selector("#tray-white button")
    box = page.locator("#tray-white button[data-piece=wq]").bounding_box()
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    page.mouse.down()
    page.mouse.move(box["x"] + 120, box["y"] - 60, steps=6)
    ghost = page.eval_on_selector(".drag-ghost", """e => {
      const s = getComputedStyle(e);
      return {bg: s.backgroundColor, border: s.borderTopWidth,
              w: e.getBoundingClientRect().width};
    }""")
    page.mouse.up()
    assert ghost["bg"] in ("rgba(0, 0, 0, 0)", "transparent"), ghost["bg"]
    assert ghost["border"] == "0px", ghost["border"]
    assert ghost["w"] < box["width"], f"ghost {ghost['w']} >= tray {box['width']}"
```

- [ ] **Step 2: Run and watch them fail**

Run: `taskset -c 0-3 make test-web`. Expected: four failures.

- [ ] **Step 3: Delete the colour-theme machinery**

```bash
git rm src/packages/web/helpmate_web/static/js/theme-toggle.js \
       src/packages/web/helpmate_web/static/js/lib/theme-mode.js \
       src/packages/web/tests/js/theme-mode.test.js \
       tests/repo/test_theme_key_not_duplicated_silently.py
```

In `index.html`: remove the `<script>` in `<head>` (the pre-paint stamper), the `#theme-toggle` button, and the `initTheme()` import and call.

In `css/app.css`: delete the whole `@media (prefers-color-scheme: dark) { … }` block and the `:root[data-theme="dark"] { … }` block. **Rewrite the comment at the top of the file** — its three-state explanation ("the viewer has THREE states, not two") is now false and would mislead the next reader. Delete the dark half of every contrast note, keeping the light measurements.

- [ ] **Step 4: The title and the footer**

`index.html`'s header becomes:

```html
<header>
  <div class="brand">
    <h1>helpmate tablebases</h1>
    <p class="tagline">Every solution to every position, precomputed.</p>
  </div>
  <nav aria-label="Screens">
    <button data-panel="explorer" class="active">Explorer</button>
    <button data-panel="puzzles">Puzzles</button>
    <button data-panel="materials">Materials</button>
    <button data-panel="mine">Search</button>
    <button data-panel="themes">Themes</button>
  </nav>
  <div class="header-end"><span id="server-chip" class="chip" hidden></span></div>
</header>
```

and gains a footer before the closing `</body>`:

```html
<footer>
  <p class="footer-corpus" id="footer-corpus"></p>
  <nav aria-label="About">
    <a href="#" data-placeholder>Source</a>
    <a href="#" data-placeholder>Dataset</a>
    <a href="#" data-placeholder>Licence</a>
  </nav>
  <p class="footer-note">Helpmate tablebases · distances in plies, h#n = 2n</p>
</footer>
```

`data-placeholder` marks a link nobody has filled in yet, so a dead link cannot ship unnoticed. Populate `#footer-corpus` from the existing `/v1/health` call in `chip.js` — one sentence naming the table count.

CSS:

```css
.brand h1 { font-size: 1.6rem; font-weight: 700; letter-spacing: -.02em; margin: 0; }
.tagline { font-size: var(--f1); }

footer {
  margin-top: var(--s4); padding: var(--s3) 1.25rem;
  border-top: 1px solid var(--rule); background: var(--panel);
  display: flex; flex-wrap: wrap; align-items: baseline; gap: var(--s3);
  font-size: var(--f1); color: var(--ink-soft);
}
footer nav { display: flex; gap: var(--s3); margin-left: auto; }
footer a { color: inherit; font-weight: 600; }
footer a:hover { color: var(--accent); }
footer a[data-placeholder] { text-decoration: underline dotted; }
```

- [ ] **Step 5: The drag ghost**

`.drag-ghost` clones the tray button, inheriting its `--sunk` fill and border. Override both, and shrink it:

```css
/* The piece in flight, not a control that has come loose: no ground, no
   border, and smaller than the tray button it came from. */
.drag-ghost {
  position: fixed; z-index: 10; width: 1.9rem; height: 1.9rem;
  pointer-events: none; opacity: .9;
  background: none; border: 0; padding: 0; box-shadow: none;
}
```

- [ ] **Step 6: Gates and commit**

Run `make lint`, `make jstest`, `make test-web`, `pytest tests/repo -v`. The repo suite drops one test (the deleted drift guard) — expected. Then commit.

---

### Task 3: Replace, never clear-then-fill

**Files:** `static/js/explorer.js`, `tests/ui/test_dashboard.py`

- [ ] **Step 1: Write the failing test**

The measured defect: `render()` empties the move list before awaiting the fetch that refills it, so everything below leaps up ~286px for ~22ms.

```python
def test_playing_a_move_never_collapses_the_move_list(page, server):
    page.goto(server)
    page.wait_for_selector("#move-list li")
    trace = page.evaluate("""() => new Promise(res => {
      const H = () => Math.round(document.getElementById('move-list').getBoundingClientRect().height);
      const seen = [];
      const t0 = performance.now();
      const tick = () => { seen.push(H());
        if (performance.now() - t0 < 1200) requestAnimationFrame(tick); else res(seen); };
      document.querySelector('#move-list section[data-group=optimal] li').click();
      tick();
    })""")
    assert min(trace) > 0, f"the move list collapsed to zero during the move: {trace[:8]}"
```

- [ ] **Step 2: Run and watch it fail** — `taskset -c 0-3 make test-web`. Expected: `min(trace)` is 0.

- [ ] **Step 3: Swap atomically**

In `render()`, delete the three synchronous clears before the `await`
(`moveList.textContent = ""`, the lines list, the themes line) and instead
build into a detached node, replacing only once the data is in hand:

```js
// Replace, never clear-then-fill. Emptying these before the await made
// everything below the list jump up ~286px for the duration of the fetch.
// The old code also cleared the move list, lines and themes but NOT the
// summary, which is why two tests were able to pass while reading the
// previous position's verdict.
const next = document.createElement("div");
renderMoveList(next, b.moves);
moveList.replaceChildren(...next.childNodes);
```

Apply the same shape to `#lines` and `#position-themes`. The `kingProblem` and
`ApiError` branches still clear explicitly — there is no replacement coming,
and leaving a previous position's moves on screen under a red banner would be
worse than an empty list.

- [ ] **Step 4: Gates and commit.**

---

### Task 4: The puzzle set and its pure logic

**Files:**
- Create: `tools/mine_puzzles.py`, `static/puzzles.epd`, `static/js/lib/puzzles.js`, `tests/js/puzzles.test.js`
- Modify: `static/js/api.js`

**Interfaces produced** (Task 5 consumes all of these):
```js
parseEpd(text)            -> [{ fen, dtm, id }]
pieceCount(fen)           -> number      // every placement char that is a letter
difficultyOf(p)           -> [dtm, pieces]
pickSession(all, n, rnd)  -> [p...]      // n puzzles, easiest first, no repeats
gradeMove(expectedUci, playedUci) -> boolean
```

**The corpus, measured — the ladder is populated at both ends:**

| pieces | h# | unique-solution positions |
|---|---|---|
| 4 | 2 | 1,691,640 |
| 5 | 3 | 152,760,522 |
| 6 | 5 | 12,190,532 |
| 6 | 8 | 53,300 |
| 6 | 8.5–9.5 | 29,996 |

2,558,313,566 with `count == 1` overall. Note 5-piece problems run **deeper** than 6-piece (h#13 vs h#9.5), so difficulty cannot be read off piece count — which is why mate length is the primary key.

- [ ] **Step 1: Decide and document the file format**

**EPD**, one position per line — the chess standard for position collections, hand-editable, and the reason is the stated future one: custom problems get added by typing a line, with no quoting or commas to get wrong.

```
8/7k/5K2/8/8/8/8/6Q1 b - - ; hm 4 ; id "KQvk.0001"
```

The subset used is exactly: the four FEN fields, then `;`-separated `key value` pairs, of which two are read — `hm` (the helpmate distance **in plies**, so `hm 4` is h#2) and `id`. Unknown keys are ignored, so future opcodes cost nothing. Document this at the top of `puzzles.epd` as a comment (`#` lines are skipped).

`hm` is stored rather than derived so that ordering 1000 puzzles costs no probes; piece count is derived from the FEN, so it is not stored.

- [ ] **Step 2: Write the failing node tests**

```js
import test from "node:test";
import assert from "node:assert/strict";
import { parseEpd, pieceCount, difficultyOf, pickSession, gradeMove }
  from "../../helpmate_web/static/js/lib/puzzles.js";

const EPD = `# a comment line is ignored
8/7k/5K2/8/8/8/8/6Q1 b - - ; hm 4 ; id "a"
7k/8/5K2/8/8/8/8/6Q1 w - - ; hm 2 ; id "b"
8/7k/5K2/8/6B1/8/8/6Q1 b - - ; hm 8 ; id "c"
`;

test("EPD parses to fen, ply distance and id, skipping comments", () => {
  const ps = parseEpd(EPD);
  assert.equal(ps.length, 3);
  assert.deepEqual(ps.map((p) => p.id), ["a", "b", "c"]);
  assert.deepEqual(ps.map((p) => p.dtm), [4, 2, 8]);
  assert.ok(ps[0].fen.startsWith("8/7k/5K2"));
});

test("an unknown opcode is ignored, not fatal — future custom fields cost nothing", () => {
  const ps = parseEpd('8/7k/5K2/8/8/8/8/6Q1 b - - ; hm 4 ; id "x" ; c0 "by A.N. Other"\n');
  assert.equal(ps.length, 1);
  assert.equal(ps[0].dtm, 4);
});

test("a malformed line is skipped rather than taking the file down", () => {
  const ps = parseEpd('garbage\n8/7k/5K2/8/8/8/8/6Q1 b - - ; hm 4 ; id "ok"\n');
  assert.deepEqual(ps.map((p) => p.id), ["ok"]);
});

test("piece count counts men, not FEN characters", () => {
  assert.equal(pieceCount("8/7k/5K2/8/8/8/8/6Q1 b - - 0 1"), 3);
  assert.equal(pieceCount("8/7k/5K2/8/6B1/8/8/6Q1 b - - 0 1"), 4);
});

test("difficulty is mate length first, piece count second", () => {
  const a = { fen: "8/7k/5K2/8/8/8/8/6Q1 b - - 0 1", dtm: 4 };   // h#2, 3 men
  const b = { fen: "8/7k/5K2/8/6B1/8/8/6Q1 b - - 0 1", dtm: 4 }; // h#2, 4 men
  const c = { fen: "8/7k/5K2/8/8/8/8/6Q1 b - - 0 1", dtm: 8 };   // h#4, 3 men
  assert.deepEqual(difficultyOf(a) < difficultyOf(b) ? "a" : "b", "a");
  const sorted = [c, b, a].sort((x, y) => (x.dtm - y.dtm) || (pieceCount(x.fen) - pieceCount(y.fen)));
  assert.deepEqual(sorted, [a, b, c]);
});

test("a session is n puzzles, easiest first, without repetition", () => {
  const all = Array.from({ length: 100 }, (_, i) => ({
    fen: "8/7k/5K2/8/8/8/8/6Q1 b - - 0 1", dtm: 2 + 2 * i, id: String(i),
  }));
  let seed = 1;
  const rnd = () => ((seed = (seed * 1103515245 + 12345) % 2147483648) / 2147483648);
  const s = pickSession(all, 10, rnd);
  assert.equal(s.length, 10);
  assert.equal(new Set(s.map((p) => p.id)).size, 10, "a puzzle repeated");
  const dtms = s.map((p) => p.dtm);
  assert.deepEqual(dtms, [...dtms].sort((a, b) => a - b), "not ordered easiest first");
});

test("a session spans the range rather than clustering at one difficulty", () => {
  const all = Array.from({ length: 100 }, (_, i) => ({
    fen: "8/7k/5K2/8/8/8/8/6Q1 b - - 0 1", dtm: 2 + 2 * i, id: String(i),
  }));
  let seed = 7;
  const rnd = () => ((seed = (seed * 1103515245 + 12345) % 2147483648) / 2147483648);
  const s = pickSession(all, 10, rnd);
  assert.ok(s[9].dtm - s[0].dtm > 100, `span too narrow: ${s[0].dtm}..${s[9].dtm}`);
});

test("a session never exceeds what the set holds", () => {
  const all = [{ fen: "8/7k/5K2/8/8/8/8/6Q1 b - - 0 1", dtm: 4, id: "only" }];
  assert.equal(pickSession(all, 10, Math.random).length, 1);
});

test("grading compares the move actually played", () => {
  assert.equal(gradeMove("h7h8", "h7h8"), true);
  assert.equal(gradeMove("h7h8", "h7h6"), false);
  assert.equal(gradeMove("e7e8q", "e7e8n"), false, "underpromotion is a different move");
});
```

- [ ] **Step 3: Run and watch them fail** — `taskset -c 0-3 make jstest`, module not found.

- [ ] **Step 4: Implement `js/lib/puzzles.js`**

```js
// The puzzle set and how a session is drawn from it. Pure -- no DOM, no
// network -- so `node --test` covers selection and grading without a browser.
//
// The set ships as EPD: one position per line, the chess-standard container
// for position collections. It is hand-editable on purpose, because custom
// problems are meant to be added by typing a line.
//
//   8/7k/5K2/8/8/8/8/6Q1 b - - ; hm 4 ; id "KQvk.0001"
//
// Exactly two opcodes are read: `hm`, the helpmate distance IN PLIES (so
// `hm 4` is h#2), and `id`. Unknown opcodes are ignored, so a future field
// costs nothing. `hm` is stored rather than probed so that ordering a
// thousand puzzles is free; piece count is derived, so it is not stored.

export function parseEpd(text) {
  const out = [];
  for (const raw of String(text || "").split("\n")) {
    const line = raw.trim();
    if (!line || line.startsWith("#")) continue;
    const [head, ...ops] = line.split(";");
    const fields = head.trim().split(/\s+/);
    // placement, side to move, castling, en passant -- EPD has no clocks, so
    // append the two the rest of this app's FEN handling expects.
    if (fields.length < 4) continue;
    const p = { fen: `${fields.slice(0, 4).join(" ")} 0 1`, dtm: null, id: null };
    for (const op of ops) {
      const t = op.trim();
      if (!t) continue;
      const key = t.split(/\s+/)[0];
      const val = t.slice(key.length).trim().replace(/^"|"$/g, "");
      if (key === "hm") p.dtm = Number(val);
      else if (key === "id") p.id = val;
    }
    if (!Number.isFinite(p.dtm) || p.dtm <= 0) continue;
    out.push(p);
  }
  return out;
}

export function pieceCount(fen) {
  const placement = String(fen || "").split(/\s+/)[0] || "";
  let n = 0;
  for (const c of placement) if (/[pnbrqk]/i.test(c)) n++;
  return n;
}

// Mate length first -- a longer helpmate is harder. Piece count second, at
// equal length. Returned as an array so callers can compare lexicographically.
export function difficultyOf(p) {
  return [p.dtm, pieceCount(p.fen)];
}

function byDifficulty(a, b) {
  const [ad, ap] = difficultyOf(a), [bd, bp] = difficultyOf(b);
  return (ad - bd) || (ap - bp);
}

// n puzzles, easiest first, no repeats, spanning the whole range rather than
// clustering: the sorted set is cut into n equal bands and one is drawn at
// random from each. This adapts to whatever the file holds, so adding custom
// problems -- or a deeper corpus -- needs no tier table to be maintained.
export function pickSession(all, n, rnd = Math.random) {
  const sorted = [...(all || [])].sort(byDifficulty);
  if (sorted.length <= n) return sorted;
  const out = [];
  const band = sorted.length / n;
  for (let i = 0; i < n; i++) {
    const lo = Math.floor(i * band);
    const hi = Math.max(lo + 1, Math.floor((i + 1) * band));
    out.push(sorted[lo + Math.floor(rnd() * (hi - lo))]);
  }
  return out;
}

export function gradeMove(expectedUci, playedUci) {
  return String(expectedUci) === String(playedUci);
}
```

- [ ] **Step 5: Run the node tests** — expect all pass.

- [ ] **Step 6: Write `tools/mine_puzzles.py`**

An offline miner, run by hand, whose output is committed. It must:

- read tables **read-only** from a `--tables` directory (default `~/tb`);
- for each requested `(material, dtm)` pair call `helpmate`'s mining API with `count=1` and a cap, take up to `--per-bucket` positions;
- walk a ladder spanning the measured corpus — 4 men at h#2 through 6 men at h#8+ — and write every result as one EPD line with `hm` and a stable `id`;
- write to a path given by `--out`, **refusing to write anywhere under `~/tb`**, mirroring the guard in `tools/bench_compression.py`;
- be deterministic given a `--seed`, so regenerating the file produces a reviewable diff rather than a reshuffle.

Target ~1000 lines. Print a summary table of what each bucket yielded so a thin bucket is visible rather than silent.

- [ ] **Step 7: Generate and commit the set**

```bash
taskset -c 0-3 python3 tools/mine_puzzles.py --tables ~/tb \
  --out src/packages/web/helpmate_web/static/puzzles.epd --seed 1
wc -l src/packages/web/helpmate_web/static/puzzles.epd
head -3 src/packages/web/helpmate_web/static/puzzles.epd
```

Record the summary table in the report. If a bucket comes back empty, say so — do not silently drop a difficulty tier.

- [ ] **Step 8: Add the fetch**

`api.js` gains `puzzles: () => fetch("/puzzles.epd").then((r) => r.text())` — a static asset, not a JSON envelope, so it does not go through `getJson`.

- [ ] **Step 9: Gates and commit.**

---

### Task 5: The puzzle screen

**Files:** create `static/js/puzzle.js`; modify `index.html`, `css/app.css`, `js/panels.js`, `tests/ui/test_dashboard.py`

**Consumes:** everything from Task 4, plus `/v1/line` for the solution and `/v1/moves` for move lookup.

- [ ] **Step 1: Write the failing tests**

```python
PUZZLE_URL = "/#panel=puzzles"


def test_a_puzzle_screen_opens_with_a_prompt_and_a_board(page, server):
    page.goto(server + PUZZLE_URL)
    page.wait_for_selector("#puzzle-board .cm-chessboard")
    prompt = page.inner_text("#puzzle-prompt")
    assert "h#" in prompt
    assert "1 of 10" in page.inner_text("#puzzle-progress")


def test_a_correct_move_is_marked_and_advances_the_line(page, server):
    page.goto(server + PUZZLE_URL)
    page.wait_for_selector("#puzzle-line .ply")
    page.click("#btn-puzzle-solution")           # reveal, then replay it
    first = page.eval_on_selector("#puzzle-line .ply", "e => e.textContent.trim()")
    assert first


def test_a_wrong_move_is_marked_and_shows_the_right_one(page, server):
    page.goto(server + PUZZLE_URL)
    page.wait_for_selector("#puzzle-line")
    # drive a deliberately wrong first move via the test hook
    page.evaluate("window.__puzzlePlay('a1a2')")
    page.wait_for_selector("#puzzle-line .ply.wrong")
    assert page.eval_on_selector_all("#puzzle-line .ply.wrong", "e => e.length") == 1
    assert page.is_visible("#puzzle-correction")


def test_exceeding_the_error_budget_reveals_the_solution(page, server):
    page.goto(server + PUZZLE_URL)
    page.wait_for_selector("#puzzle-line")
    page.evaluate("window.__puzzleSetBudget(1)")
    page.evaluate("window.__puzzlePlay('a1a2')")
    page.evaluate("window.__puzzlePlay('a1a3')")
    page.wait_for_selector("#puzzle-line.revealed")
```

`window.__puzzlePlay(uci)` and `window.__puzzleSetBudget(n)` are deliberate
test hooks — driving a *wrong* drag through the board is unreliable, and the
grading logic is what these tests exist to pin. Document them as such in the
source.

- [ ] **Step 2: Run and watch them fail.**

- [ ] **Step 3: Markup**

A new panel mirroring the explorer's rail/readout so the two screens read as
one product:

```html
  <section id="panel-puzzles" hidden>
    <div class="rail board-col">
      <div class="board-pin">
        <div id="puzzle-board"></div>
      </div>
    </div>
    <div class="readout side">
      <p id="puzzle-progress" class="eyebrow"></p>
      <p id="puzzle-prompt" class="verdict"></p>
      <ol id="puzzle-line"></ol>
      <p id="puzzle-correction" hidden class="hint"></p>
      <div class="row">
        <button type="button" id="btn-puzzle-solution">Show solution</button>
        <button type="button" id="btn-puzzle-next">Next puzzle</button>
      </div>
    </div>
  </section>
```

- [ ] **Step 4: Implement `js/puzzle.js`**

Behaviour, in order:

1. On first activation, fetch `puzzles.epd`, parse, and `pickSession(all, 10)`.
2. For the current puzzle: set the board, write the prompt (`KQvk · h#2 · one solution` and whose move it is), and fetch its solution with `api.line(fen)` — `count == 1`, so one line.
3. The solver plays **every ply**, both colours. After each drag, look up the played move in the current `/v1/moves` response to get its UCI, and compare against the expected ply's UCI (derived by matching the solution's SAN in that same response).
4. Correct → mark the ply with a check, advance, play it on the board.
5. Wrong → mark a cross, show the correct move in `#puzzle-correction`, increment the error count, and leave the position where it was.
6. Errors **above the budget** (default 1, settable) → add `revealed` to `#puzzle-line` and play out the remaining line.
7. **Show solution** reveals immediately; **Next puzzle** advances, and after the tenth says the session is done and offers to start another.

Keep the board construction identical to the explorer's — same `assetsUrl`,
same `BORDER_TYPE.none`, so the coordinates sit inside the squares as they do
on the other screen.

- [ ] **Step 5: Register the panel** in `panels.js`'s id list and the nav.

- [ ] **Step 6: Style it** using existing tokens only: `.ply` marks reuse the
ink scale (a check at `--ink`, a cross at `--flag`, which is already the
error colour and is not a new value).

- [ ] **Step 7: Gates, a screenshot, and commit.** Look at it beside the
explorer at 1280px and 420px and say whether they read as the same product.

---

### Task 6: The motif documentation screen, docs, version and gate

**Files:** create `static/js/themes-doc.js`; modify `index.html`, `css/app.css`, `js/panels.js`, `README.md`, `docs/USAGE.md`, `CHANGELOG.md`, `VERSION`, the eight version sites, `tests/ui/test_dashboard.py`

- [ ] **Step 1: Write the failing test**

```python
def test_the_themes_screen_explains_every_motif_the_build_detects(page, server):
    page.goto(f"{server}/#panel=themes")
    page.wait_for_selector("#themes-doc .theme-entry")
    names = page.eval_on_selector_all("#themes-doc .theme-entry h3",
                                      "els => els.map(e => e.textContent.trim())")
    api = page.evaluate("""async () => (await (await fetch('/v1/themes')).json())
                             .themes.map(t => t.name)""")
    assert sorted(names) == sorted(api), f"{len(names)} documented vs {len(api)} detected"
    # every entry says what it reads, because that decides whether it can
    # answer on a saturated position
    needs = page.eval_on_selector_all("#themes-doc .theme-needs", "e => e.length")
    assert needs == len(api)
```

- [ ] **Step 2: Run and watch it fail.**

- [ ] **Step 3: Implement `js/themes-doc.js`**

Render from `/v1/themes` — never a hardcoded list, so it cannot drift from the
binary. Group the motifs, with a sentence introducing each group before its
members:

- **the mate picture** — `pure`, `model`, `ideal`, `mirror`
- **the move sequence** — `switchback`, `closed-walk`, `excelsior`, `promotion`, `underpromotion`
- **the position's structure** — `set-play`, `single-piece`

Anything the API returns that is not in a known group falls into a final
"other" group rather than being dropped — a new motif must appear without a
code change here.

Each entry shows the name, the definition from the API, and its `needs` value
with a one-line explanation of what that means for saturated positions.

- [ ] **Step 4: Docs**

`README.md` and `docs/USAGE.md`: document the puzzle screen (one-solution
positions, ten per session ordered by difficulty, the error budget), the motif
screen, the footer, and that there is now **one palette and no colour-theme
control**. Say plainly that the puzzle set is a committed EPD file and how to
regenerate it.

- [ ] **Step 5: Version bump to 0.13.0 — eight sites**

```
pyproject.toml:7 · VERSION:1 · src/packages/web/pyproject.toml:7
src/packages/web/helpmate_web/__init__.py:8 · src/packages/api/pyproject.toml:7
src/packages/api/pyproject.toml:16   <- THE PIN: helpmate>=0.12.0,<0.13 -> >=0.13.0,<0.14
README.md (the `helpmate themes` provenance line, after re-running it)
docs/USAGE.md (the /v1/health sample output)
```

**Do not touch** the `"Since v0.11.0"` / `"Since v0.12.0"` historical markers
in `docs/USAGE.md`, nor `test_api_stats.py`'s fixture `generator_version`.
Those record when features shipped; rewriting them falsifies the history.

- [ ] **Step 6: The full gate, in the foreground**

```
make lint · make typecheck · make jstest · pytest tests/repo -v
pytest src/packages/api/tests -v · make test-web · make format-check
```

Plus the accent-guard mutation: inject `background: var(--accent);` into a
`.move-group > ul > li.optimal` rule, confirm the repo test FAILS, revert,
confirm it PASSES, and **confirm `git status` is clean before committing**.

- [ ] **Step 7: Look at every screen** — explorer, puzzles, materials, search,
themes at 1280px, plus explorer and puzzles at 420px. One palette now, so
there is no dark variant to check. Report what you saw per image.

- [ ] **Step 8: Commit.**

---

## Self-Review

**Spec coverage**

| Spec section | Task |
|---|---|
| The measured jump; replace-never-clear | 3 |
| Colour theme switch and dark mode deleted | 2 |
| Title, footer, drag ghost | 2 |
| Puzzles: one-solution only, whole line, both colours | 5 |
| Grading, check/cross, error budget, reveal | 4 (logic), 5 (screen) |
| Ten per session, random, increasing difficulty | 4 |
| Static EPD set, hand-editable, no new endpoint | 4 |
| Puzzle screen resembles the explorer | 5 |
| Motif documentation from `/v1/themes` | 6 |
| v0.12.0 review blockers H1, M6, M5 | 1 |

**Type consistency** — `parseEpd`/`pieceCount`/`difficultyOf`/`pickSession`/`gradeMove` are defined in Task 4 Step 4 and consumed in Task 5 Step 4 under exactly those names. `api.puzzles()` is added in Task 4 Step 8 and called in Task 5 Step 4.

**Ordering** — Task 1 first (it unblocks the v0.12.0 merge). 4 before 5. 2 before 6 (the docs describe the deleted control). 6 last.

**Known risks carried deliberately**

- Task 4's miner runs against a live corpus while a generation job is writing to `~/tb`. It is read-only and must stay so; the plan names the guard.
- The puzzle screen builds a second `Chessboard` instance. If the two ever need to share state they should not — they are separate screens, and the explorer's `current`/`history` must not leak into the puzzle flow.
- `window.__puzzlePlay` is a test hook in shipped code. It is documented as one; if that is unacceptable, the alternative is driving wrong moves through real drags, which is exactly the flakiness the previous plan spent two rounds on.
