# Dashboard Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the three-panel dashboard into something publishable — a move list that is grouped and sorted so row one is the answer, a palette taken from lichess, an ordinal encoded without hue, a responsive two-pane shell, and a working dark-mode toggle.

**Architecture:** No build step, no framework, no npm — the same vanilla ES modules served statically. The feature (grouping and ordering) goes into a new **pure** module `js/lib/moves.js` so `node --test` covers it with no browser, matching the existing `lib/stats.js` / `lib/themes.js` pattern; `explorer.js` becomes a dumb renderer over it. `app.css` is rewritten as a token system. The dark-mode toggle gets its own pure module plus a thin DOM wrapper.

**Tech Stack:** ES modules (no bundler), CSS custom properties, `node --test` for JS units, Playwright (headless Chromium) for UI, pytest for both.

## Global Constraints

- **Every build/test command runs under `taskset -c 0-3`.** Do not exceed four cores.
- **Never write to `~/tb` or `~/tb/raw`.** A long 6-piece generation run writes there. Reading and probing are fine. Scratch goes in `$(mktemp -d)`; never `rm -rf /tmp/tmp.*`.
- Never run bare `./build/helpmate_tests` — always `"~[slow]"` or a specific tag. Not expected to be needed: this plan touches no C++.
- `ctest` runs **without** `-j` (documented shared-temp-dir race in `test_probe.cpp`).
- No CMake FetchContent / GitHub clones. Use `GIT_CONFIG_GLOBAL=/dev/null` for any pip install.
- Commit trailer on every commit: `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`
- **No npm, no new dependency of any kind.** The benchmark ships drag-and-drop chess, live probing, history and dark mode in 22.5 KB gzipped with three HTTP requests; that is the bar.
- Accent colour is used for links, focus rings and hover borders **only**. Never a field, never a header fill, never the move list, never a chart series.

## The fixture positions — measured, not derived

Every FEN below was probed against `~/tb/KQvk.hm` on 2026-08-11 via the Python
bindings (`helpmate.Tablebase(...).moves(fen)`). The UI test fixture
(`tests/ui/conftest.py`) generates `KQvk` fresh, and generation is
deterministic, so these values must reproduce — **but confirm by running the
test, never by assuming.** Values are given in *generator emission order*,
which is what the dashboard renders today.

**A. Landing position** — `8/7k/5K2/8/8/8/8/6Q1 b - - 0 1` · probe `dtm 8→ (2, 4)`

| san | dtm | count | solvable | optimal | group |
|---|---|---|---|---|---|
| `Kh6` | 1 | 3 | yes | yes | Optimal |
| `Kh8` | 1 | 1 | yes | yes | Optimal |

Sorted by ascending `count`: **Kh8 then Kh6** — the reverse of today's order.
This is the minimal proof the sort runs.

**B. All three groups, richly** — `7k/8/5K2/8/8/8/8/6Q1 w - - 0 1` · probe `(1, 1)`

Reached from A by playing `Kh8`. 28 legal moves:

- **Optimal (1):** `Qg7#` dtm 0, count 1 → badge `h#0 · only reply`
- **Slower (25):** dtm 2 — `Kf7`(3), `Qa7`(1), `Qg2`(1), `Qg3`(1), `Qg4`(1), `Qg5`(1); dtm 4 — `Ke5`(5), `Kg5`(9), `Ke6`(10), `Kf5`(11), `Ke7`(13), `Kg6`(27), `Qb1`(29), `Qh2+`(30), `Qh1+`(31), `Qa1`(46), `Qf1`(50), `Qc1`(52), `Qe1`(54), `Qf2`(60), `Qb6`(60), `Qd1`(62), `Qd4`(66), `Qe3`(67), `Qc5`(67)
- **No mate (2):** `Qg6`, `Qg8+`

**C. Saturated optimal child** — `8/8/7k/8/8/8/8/KQ6 b - - 0 1` · probe `(10, 255)`

| san | dtm | count | optimal | group |
|---|---|---|---|---|
| `Kg5` | 9 | **255** | yes | Optimal |
| `Kh5` | 9 | 246 | yes | Optimal |
| `Kg7` | 11 | 255 | no | Slower |

Sorted: **Kh5 (246) then Kg5 (255+)**. This is the fixture that proves a
saturated count renders as `255+ ways` and never `255 ways`, and it also
reverses the generator's order.

**D. A dead move that changes material** — `8/8/8/8/8/8/4k3/K2Q4 b - - 0 1` · probe `(8, 16)`
`Kf2` dtm 9 count 255 (Slower) · `Ke3` dtm 7 count 16 (Optimal) · `Kxd1` unsolvable (No mate).
`Kxd1` reaches `Kvk`, which the KQvk closure also generates, so the fixture
answers it. Kept as a compact three-group case.

A mate child carries `count == 1` (measured: `Qg7#` above), so no optimal move
ever has `count == 0` and the badge rule below is total.

---

### Task 1: The grouping and ordering, as a pure module

**Files:**
- Create: `src/packages/web/helpmate_web/static/js/lib/moves.js`
- Test: `src/packages/web/tests/js/moves.test.js`

**Interfaces:**
- Consumes: nothing. Pure functions over the move objects `/v1/moves` returns:
  `{uci, san, fen, dtm: number|null, count: number, solvable: boolean, optimal: boolean, notation: string|null}`.
- Produces, for Task 2 and Task 6:
  - `COUNT_SAT: 255`
  - `groupMoves(moves: Move[]) -> {key: "optimal"|"slower"|"dead", label: string, moves: Move[]}[]` — non-empty groups only, in fixed order
  - `waysLabel(count: number) -> string`
  - `moveBadge(move: Move) -> string`
  - `moveClass(move: Move) -> string` — the `class` attribute for the row

- [ ] **Step 1: Write the failing test**

Create `src/packages/web/tests/js/moves.test.js`:

```js
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  COUNT_SAT, groupMoves, waysLabel, moveBadge, moveClass,
} from "../../helpmate_web/static/js/lib/moves.js";

// Every fixture below is real /v1/moves output, probed against KQvk on
// 2026-08-11. See the plan's "fixture positions" table.

// 8/7k/5K2/8/8/8/8/6Q1 b -- the landing position, in generator order.
const LANDING = [
  { san: "Kh6", dtm: 1, count: 3, solvable: true, optimal: true, notation: "h#0.5" },
  { san: "Kh8", dtm: 1, count: 1, solvable: true, optimal: true, notation: "h#0.5" },
];

// 8/8/7k/8/8/8/8/KQ6 b -- an optimal child whose count has saturated.
const SATURATED = [
  { san: "Kg5", dtm: 9, count: 255, solvable: true, optimal: true, notation: "h#4.5" },
  { san: "Kh5", dtm: 9, count: 246, solvable: true, optimal: true, notation: "h#4.5" },
  { san: "Kg7", dtm: 11, count: 255, solvable: true, optimal: false, notation: "h#5.5" },
];

// 8/8/8/8/8/8/4k3/K2Q4 b -- one move in each group. Kxd1 reaches Kvk.
const THREE = [
  { san: "Kf2", dtm: 9, count: 255, solvable: true, optimal: false, notation: "h#4.5" },
  { san: "Ke3", dtm: 7, count: 16, solvable: true, optimal: true, notation: "h#3.5" },
  { san: "Kxd1", dtm: null, count: 0, solvable: false, optimal: false, notation: null },
];

test("the optimal group is ordered by ascending child count", () => {
  const [optimal] = groupMoves(LANDING);
  assert.equal(optimal.key, "optimal");
  // Kh8 has one continuation, Kh6 has three: the more forcing move leads.
  // The generator emitted them the other way round.
  assert.deepEqual(optimal.moves.map((m) => m.san), ["Kh8", "Kh6"]);
});

test("groups appear in fixed order, and empty groups are omitted", () => {
  assert.deepEqual(groupMoves(THREE).map((g) => [g.key, g.label]),
                   [["optimal", "Optimal"], ["slower", "Slower"], ["dead", "No mate"]]);
  // The landing position has only optimal moves.
  assert.deepEqual(groupMoves(LANDING).map((g) => g.key), ["optimal"]);
  assert.deepEqual(groupMoves([]), []);
  assert.deepEqual(groupMoves(undefined), []);
});

test("the slower group is ordered by dtm, then count, then san", () => {
  const moves = [
    { san: "Qb1", dtm: 4, count: 29, solvable: true, optimal: false, notation: "h#2" },
    { san: "Kf7", dtm: 2, count: 3, solvable: true, optimal: false, notation: "h#1" },
    { san: "Qg5", dtm: 2, count: 1, solvable: true, optimal: false, notation: "h#1" },
    { san: "Qa7", dtm: 2, count: 1, solvable: true, optimal: false, notation: "h#1" },
  ];
  const [slower] = groupMoves(moves);
  // dtm 2 before dtm 4; inside dtm 2, count 1 before count 3; the two count-1
  // moves are separated by san.
  assert.deepEqual(slower.moves.map((m) => m.san), ["Qa7", "Qg5", "Kf7", "Qb1"]);
});

test("dead moves sort by san alone and never reach a numeric comparison", () => {
  // dtm is null for every unsolvable move. If the dead group ever used the
  // dtm comparator, null - null is 0 and the order would silently become
  // input order -- so assert a case where san order differs from input order.
  const moves = [
    { san: "Qg8+", dtm: null, count: 0, solvable: false, optimal: false, notation: null },
    { san: "Qg6", dtm: null, count: 0, solvable: false, optimal: false, notation: null },
  ];
  const [dead] = groupMoves(moves);
  assert.equal(dead.key, "dead");
  assert.deepEqual(dead.moves.map((m) => m.san), ["Qg6", "Qg8+"]);
});

test("groupMoves does not mutate its argument", () => {
  const input = LANDING.map((m) => ({ ...m }));
  const order = input.map((m) => m.san);
  groupMoves(input);
  assert.deepEqual(input.map((m) => m.san), order);
});

test("a saturated count is never rendered as a measurement", () => {
  assert.equal(waysLabel(255), "255+ ways");
  assert.equal(waysLabel(COUNT_SAT), "255+ ways");
  assert.equal(waysLabel(254), "254 ways");
  assert.equal(waysLabel(1), "only reply");
  assert.equal(waysLabel(2), "2 ways");
});

test("badges state a claim, and the optimal group is sorted around them", () => {
  const [optimal, slower] = groupMoves(SATURATED);
  assert.deepEqual(optimal.moves.map(moveBadge),
                   ["h#4.5 · 246 ways", "h#4.5 · 255+ ways"]);
  assert.deepEqual(slower.moves.map(moveBadge), ["h#5.5 · slower"]);
});

test("a slower badge omits the count, a dead badge omits everything", () => {
  const [, slower, dead] = groupMoves(THREE);
  assert.equal(moveBadge(slower.moves[0]), "h#4.5 · slower");
  assert.equal(moveBadge(dead.moves[0]), "no mate");
});

test("moveClass carries the group and marks a sole continuation", () => {
  assert.equal(moveClass(LANDING[1]), "optimal only");   // Kh8, count 1
  assert.equal(moveClass(LANDING[0]), "optimal");        // Kh6, count 3
  assert.equal(moveClass(THREE[0]), "slower");
  assert.equal(moveClass(THREE[2]), "dead");
});
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
taskset -c 0-3 node --test src/packages/web/tests/js/moves.test.js
```

Expected: FAIL — `Cannot find module .../js/lib/moves.js`.

- [ ] **Step 3: Write the module**

Create `src/packages/web/helpmate_web/static/js/lib/moves.js`:

```js
// Grouping and ordering of the legal-move list. Pure -- no DOM, no network --
// so `node --test` covers the whole feature without a browser, and explorer.js
// stays a renderer that knows nothing about what makes a move good.

// The stored optimal-line count saturates here (COUNT_SAT in
// src/core/chess/types.h). A saturated count means "cannot be enumerated",
// not "there are exactly 255", so it must never be rendered as a plain
// number -- the whole project treats the ceiling as an absence of data.
export const COUNT_SAT = 255;

// Ordering inside a group breaks ties on the SAN by plain code-unit
// comparison, never localeCompare: locale-dependent collation would make the
// rendered order depend on the machine the browser runs on, and these lists
// are asserted element-by-element by the tests.
function bySan(a, b) {
  if (a.san < b.san) return -1;
  if (a.san > b.san) return 1;
  return 0;
}

const GROUPS = [
  {
    key: "optimal",
    label: "Optimal",
    holds: (m) => m.optimal === true,
    // dtm is CONSTANT across this group -- every optimal move leads to a
    // child at dtm = D - 1 -- so mate length cannot order it. The child's
    // solution count can: it says how forcing the move is, which is also the
    // property a composer cares about. So the ordering doubles as the advice.
    order: (a, b) => (a.count - b.count) || bySan(a, b),
  },
  {
    key: "slower",
    label: "Slower",
    holds: (m) => m.solvable === true && m.optimal !== true,
    order: (a, b) => (a.dtm - b.dtm) || (a.count - b.count) || bySan(a, b),
  },
  {
    key: "dead",
    label: "No mate",
    holds: (m) => m.solvable !== true,
    // Every move here has dtm null, so it must never reach a numeric
    // comparator: null - null is 0, which would silently degrade to input
    // order rather than failing loudly.
    order: bySan,
  },
];

// Non-empty groups, in fixed order. `filter` copies, so the caller's array is
// never reordered -- the drag-to-play path in explorer.js reads the same
// array and relies on it being untouched.
export function groupMoves(moves) {
  const out = [];
  for (const g of GROUPS) {
    const rows = (moves || []).filter(g.holds).sort(g.order);
    if (rows.length) out.push({ key: g.key, label: g.label, moves: rows });
  }
  return out;
}

export function waysLabel(count) {
  if (count >= COUNT_SAT) return `${COUNT_SAT}+ ways`;
  return count === 1 ? "only reply" : `${count} ways`;
}

// A badge states a claim, never a bare number -- and a metric is omitted
// where it would mislead. A slower move's child count is not comparable with
// the optimal group's (they sit at different distances), so it is left off.
export function moveBadge(move) {
  if (move.solvable !== true) return "no mate";
  if (move.optimal !== true) return `${move.notation} · slower`;
  return `${move.notation} · ${waysLabel(move.count)}`;
}

// The row's class. "only" marks a child with a single continuation; it is
// drawn as a ring rather than a colour, so nothing is encoded by hue alone.
export function moveClass(move) {
  if (move.solvable !== true) return "dead";
  if (move.optimal !== true) return "slower";
  return move.count === 1 ? "optimal only" : "optimal";
}
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
taskset -c 0-3 node --test src/packages/web/tests/js/moves.test.js
```

Expected: PASS, 9 tests.

- [ ] **Step 5: Prove the tests can fail — mutation check**

The lesson this project keeps relearning is that nothing is caught by writing
a check, only by running it. Apply each mutation, confirm a **named** test
fails, then revert:

| # | mutation in `lib/moves.js` | must fail |
|---|---|---|
| 1 | optimal `order` → `bySan` (drop the count key) | "the optimal group is ordered by ascending child count" |
| 2 | `waysLabel`'s `>=` → `>` | "a saturated count is never rendered as a measurement" |
| 3 | slower `order` → `(a, b) => (a.count - b.count) \|\| bySan(a, b)` (drop dtm) | "the slower group is ordered by dtm, then count, then san" |
| 4 | dead `order` → the slower comparator | "dead moves sort by san alone…" |
| 5 | `moveClass` drops the `count === 1` branch | "moveClass carries the group and marks a sole continuation" |

Run after each: `taskset -c 0-3 node --test src/packages/web/tests/js/moves.test.js`.
If any mutation survives, the test is wrong — strengthen it before continuing.
Record the five results in the task's review notes.

- [ ] **Step 6: Lint**

```bash
taskset -c 0-3 make lint
```

Expected: exit 0. (`lint` copies each JS file to a `.mjs` temp path so
`node --check` parses it as unambiguous ESM — a syntax error after the first
`export` is otherwise silently accepted.)

- [ ] **Step 7: Commit**

```bash
git add src/packages/web/helpmate_web/static/js/lib/moves.js \
        src/packages/web/tests/js/moves.test.js
git commit -m "feat(web): group and order the move list, as a pure module

Optimal / Slower / No mate, each with its own key. Inside the optimal group
the key is the child's solution count, ascending -- mate length is constant
there by construction (every optimal move leads to dtm = D - 1), so it cannot
order anything, while the count says how forcing the move is.

A saturated count renders as 255+ and never 255: the ceiling is an absence of
data, not a measurement.

Pure, so node --test covers the whole feature with no browser. Fixtures are
real /v1/moves output probed against KQvk, listed in the plan.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Render the grouped list

**Files:**
- Modify: `src/packages/web/helpmate_web/static/index.html:76` (`<ul id="move-list">` → `<div>`), `:77-80` (delete the legend)
- Modify: `src/packages/web/helpmate_web/static/js/explorer.js:12` (import), `:147-159` (the render loop)
- Modify: `src/packages/web/tests/ui/test_dashboard.py` (new cases appended)

**Interfaces:**
- Consumes: `groupMoves`, `moveBadge`, `moveClass` from Task 1.
- Produces: the DOM contract every later task and every UI test depends on —

```html
<div id="move-list">
  <section class="move-group" data-group="optimal">
    <h3 class="eyebrow">Optimal <span class="n">2</span></h3>
    <ul>
      <li class="optimal only" data-san="Kh8">
        <span class="san">Kh8</span><span class="badge">h#0.5 · only reply</span>
      </li>
    </ul>
  </section>
</div>
```

**The contract that must not break.** Seven UI tests use
`page.wait_for_selector("#move-list li")` as their "page is ready" idiom, two
count `#move-list li`, and one maps `dataset.san` across every match. So the
group header is the `<h3>` of the section, **outside** the `<ul>` — never an
`<li>`. `#move-list li` therefore still selects exactly the move rows.
`#move-list` changing from `<ul>` to `<div>` is invisible to all of them.

- [ ] **Step 1: Write the failing tests**

Append to `src/packages/web/tests/ui/test_dashboard.py`:

```python
SATURATED = "8/8/7k/8/8/8/8/KQ6 b - - 0 1"
THREE_GROUPS = "7k/8/5K2/8/8/8/8/6Q1 w - - 0 1"


def _rows(page, selector="#move-list li"):
    return page.eval_on_selector_all(selector, "els => els.map(e => e.dataset.san)")


def test_optimal_moves_are_ordered_by_ascending_child_count(page, server):
    # Landing position: Kh6 has 3 optimal continuations, Kh8 has 1, and the
    # move generator emits them in that (wrong) order. Kh8 is the more forcing
    # move and must lead. Measured against KQvk on 2026-08-11.
    page.goto(server)
    page.wait_for_selector("#move-list li")
    assert _rows(page, "#move-list section[data-group=optimal] li") == ["Kh8", "Kh6"]


def test_a_saturated_child_count_renders_as_a_ceiling_not_a_number(page, server):
    # 8/8/7k/8/8/8/8/KQ6 b: Kg5 leads to a child whose count has saturated at
    # 255, Kh5 to one with 246. The saturated move must sort last (255 > 246)
    # and must never claim "255 ways" -- a ceiling is not a measurement.
    page.goto(f"{server}/#fen={quote(SATURATED)}")
    page.wait_for_selector("#move-list li")
    optimal = "#move-list section[data-group=optimal] li"
    assert _rows(page, optimal) == ["Kh5", "Kg5"]
    badges = page.eval_on_selector_all(
        f"{optimal} .badge", "els => els.map(e => e.textContent)")
    assert badges == ["h#4.5 · 246 ways", "h#4.5 · 255+ ways"]
    assert not any(b.endswith("255 ways") for b in badges)


def test_all_three_groups_render_in_order_with_counted_headers(page, server):
    # 7k/8/5K2/8/8/8/8/6Q1 w -- the position after Kh8. 28 legal moves:
    # one optimal (Qg7#), 25 slower, 2 that lead nowhere.
    page.goto(f"{server}/#fen={quote(THREE_GROUPS)}")
    page.wait_for_selector("#move-list li")
    groups = page.eval_on_selector_all(
        "#move-list section.move-group", "els => els.map(e => e.dataset.group)")
    assert groups == ["optimal", "slower", "dead"]

    headers = page.eval_on_selector_all(
        "#move-list section.move-group h3", "els => els.map(e => e.textContent)")
    assert headers == ["Optimal 1", "Slower 25", "No mate 2"]

    # Row one is the answer, whatever the generator emitted.
    assert _rows(page)[0] == "Qg7#"
    assert page.eval_on_selector(
        "#move-list li .badge", "e => e.textContent") == "h#0 · only reply"

    # The slower group is ordered by mate length first, then by count.
    assert _rows(page, "#move-list section[data-group=slower] li")[:6] == [
        "Qa7", "Qg2", "Qg3", "Qg4", "Qg5", "Kf7"]
    assert _rows(page, "#move-list section[data-group=dead] li") == ["Qg6", "Qg8+"]


def test_the_group_header_is_not_a_move_row(page, server):
    # The whole DOM contract in one assertion: three headers exist, and
    # `#move-list li` still counts exactly the 28 moves and nothing else.
    page.goto(f"{server}/#fen={quote(THREE_GROUPS)}")
    page.wait_for_selector("#move-list li")
    assert page.eval_on_selector_all("#move-list section.move-group h3",
                                     "els => els.length") == 3
    sans = _rows(page)
    assert len(sans) == 28
    assert all(sans), "every #move-list li must carry a data-san"
```

- [ ] **Step 2: Run them to verify they fail**

```bash
taskset -c 0-3 python -m pytest src/packages/web/tests/ui/test_dashboard.py \
  -k "ascending_child_count or saturated_child or three_groups or group_header" -v
```

Expected: FAIL — `#move-list section[data-group=optimal]` never matches
(today's `#move-list` is a flat `<ul>` of `<li>`).

- [ ] **Step 3: Change the container in `index.html`**

Replace lines 75-80 (the `Moves` heading, the list, and the legend) with:

```html
      <h2 class="eyebrow">Moves</h2>
      <div id="move-list"></div>
```

The legend is deleted, not restyled: the group headers **are** the legend now,
and they say it in words rather than in colour. Its CSS block goes in Task 3.

- [ ] **Step 4: Render the groups in `explorer.js`**

Add to the imports at line 12:

```js
import { groupMoves, moveBadge, moveClass } from "./lib/moves.js";
```

Replace lines 147-159 (the `for (const m of b.moves)` loop and the
`if (!b.moves.length)` block) with a call:

```js
  renderMoveList(moveList, b.moves);
```

and add this function above `render()` (after `syncControls`):

```js
// #move-list is a <div> of <section class="move-group">, not a <ul>. Seven UI
// tests use `#move-list li` as their "the page is ready" idiom and two COUNT
// it, so a group header must never be an <li> -- it is the section's <h3>,
// outside the <ul>. `#move-list li` then still selects exactly the move rows.
function renderMoveList(el, moves) {
  el.textContent = "";
  const groups = groupMoves(moves);
  if (!groups.length) {
    // A mated or stalemated position has no legal moves. Say so as prose: an
    // <li> here would be counted as a move by every selector above.
    const p = document.createElement("p");
    p.className = "empty";
    p.textContent = "no legal moves — this position is mate or stalemate";
    el.appendChild(p);
    return;
  }
  for (const g of groups) {
    const sec = document.createElement("section");
    sec.className = "move-group";
    sec.dataset.group = g.key;

    const h = document.createElement("h3");
    h.className = "eyebrow";
    h.append(g.label, " ");
    const n = document.createElement("span");
    n.className = "n";
    n.textContent = g.moves.length;
    h.appendChild(n);

    const ul = document.createElement("ul");
    for (const m of g.moves) {
      const li = document.createElement("li");
      li.className = moveClass(m);
      li.dataset.san = m.san;
      const san = document.createElement("span");
      san.className = "san";
      san.textContent = m.san;
      const badge = document.createElement("span");
      badge.className = "badge";
      badge.textContent = moveBadge(m);
      li.append(san, badge);
      // Every row is clickable, including the dead ones: walking into a
      // position with no helpmate is a legitimate thing to want to look at,
      // and that is the behaviour the list has today.
      li.addEventListener("click", () => { history.push(current); render(m.fen); });
      ul.appendChild(li);
    }
    sec.append(h, ul);
    el.appendChild(sec);
  }
}
```

`h.append(g.label, " ")` before the `<span class="n">` is what makes
`h3.textContent` read `"Optimal 1"` — the assertion in Step 1.

- [ ] **Step 5: Run the new tests to verify they pass**

```bash
taskset -c 0-3 python -m pytest src/packages/web/tests/ui/test_dashboard.py \
  -k "ascending_child_count or saturated_child or three_groups or group_header" -v
```

Expected: PASS, 4 tests.

- [ ] **Step 6: Run the whole UI suite untouched — this is the contract check**

```bash
taskset -c 0-3 python -m pytest src/packages/web/tests/ui -v
```

Expected: PASS, 20 tests (16 existing + 4 new), **with no edit to any
pre-existing test**. If a count assertion moved, the structure is wrong, not
the test — go back to Step 4. Do not relax an assertion to make it pass.

- [ ] **Step 7: Commit**

```bash
git add src/packages/web/helpmate_web/static/index.html \
        src/packages/web/helpmate_web/static/js/explorer.js \
        src/packages/web/tests/ui/test_dashboard.py
git commit -m "feat(web): render the move list grouped and sorted

Rows rendered in generator order meant the only move keeping the shortest
mate could sit fourth, under three that throw a move away, distinguished by
nothing but a faint border. Now: Optimal / Slower / No mate, counted headers,
row one is always the answer.

#move-list becomes a <div> of <section class=move-group>, but the header is
the section's <h3> and stays outside the <ul>, so `#move-list li` still
selects exactly the move rows -- the idiom seven UI tests are built on. All 16
existing tests pass unedited.

The legend is deleted rather than restyled: the group headers say in words
what it said in colour.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Tokens and the lichess palette

**Files:**
- Modify: `src/packages/web/helpmate_web/static/css/app.css:1-40` (header comment and every palette block), `:144-159` (move list and legend), `:207-215` (histogram fills)

**Interfaces:**
- Consumes: the `.move-group` / `.san` / `.badge` / `.only` structure from Task 2.
- Produces: the token names every later task styles through — `--ground`,
  `--panel`, `--sunk`, `--ink`, `--ink-soft`, `--ink-faint`, `--rule`,
  `--rule-strong`, `--accent`, `--accent-soft`, `--on-ink`, `--flag`,
  `--flag-soft`, `--info-soft`, `--f0`…`--f4`, `--s1`…`--s5`, `--r`.

- [ ] **Step 1: Replace the palette blocks**

Replace `app.css` lines 1-40 (the header comment through the
`:root[data-theme="light"]` block) with:

```css
/* helpmate dashboard.
   An instrument, not an essay: one sans for the interface, monospace for
   everything that is data.

   The palette is lichess's, read off its shipped theme
   (ui/lib/css/theme/_theme.default.scss and _theme.light.scss). Two rules
   run the whole system:

     1. GROUNDS carry one hue -- 37deg, at 5-10% saturation. Lichess declares
        it once as ---site-hue and derives every surface from it.
     2. INK AND RULES are exactly achromatic -- hue 0, saturation 0.

   That split is why the page reads warm while no text ever looks tinted. The
   palette this replaced was hue 37 as well, at 30-40% saturation, which is
   the difference between a tint and a colour.

   ONE accent, and it is blue. Every instrument surveyed lands in hue
   203-220deg: Primer #0969da, Grafana #1f62e0, Datasette #276890, lichess
   #1b78d0. The discipline is not desaturation -- those run 56-93% saturated
   -- it is hue-lock plus restraint about placement. Here the accent touches
   links, focus rings and hover borders. It is never a field, never a header
   fill, and never the move list: that ordinal carries no hue at all (see
   "move list" below).

   syzygy-tables.info's dark mode IS this palette -- #161512, #262421,
   #bababa, #404040, #3692e7 all match lichess exactly -- so adopting it makes
   us consistent with the nearest neighbour tool rather than merely inspired
   by it. Its light mode is stock Bootstrap 3 and is not copied.

   --flag stays, achromatic-adjacent and used for exactly one thing: the
   error banner and the "server unreachable" chip. An error is the one place
   on this page where a warning hue is telling the truth. */

:root {
  --ground: #edebe9;
  --panel: #ffffff;
  --sunk: #f5f4f2;
  --ink: #2b2b2b;
  --ink-soft: #6b6b6b;
  --ink-faint: #949494;
  --rule: #d9d9d9;
  --rule-strong: #b4b4b4;
  --accent: #1b78d0;
  --accent-soft: #e3eef9;
  --on-ink: #ffffff;
  --flag: #b3261e;
  --flag-soft: #fbeae9;
  --info-soft: #e3eef9;

  /* Type scale. Replaces twelve ad-hoc rem values (.7 .74 .76 .78 .8 .82
     .84 .85 .86 .88 .9 .95 1.05 1.15). */
  --f0: .75rem;   /* eyebrows, chips, tile keys */
  --f1: .82rem;   /* data rows, hints, form labels */
  --f2: .9rem;    /* help copy, verdicts, inputs */
  --f3: 1rem;     /* emphasised data */
  --f4: 1.15rem;  /* headings */

  /* Spacing scale. --step was declared and never used; this replaces it. */
  --s1: .35rem;
  --s2: .6rem;
  --s3: 1rem;
  --s4: 1.6rem;
  --s5: 2.6rem;

  /* Instruments have small radii: lichess ships 7px, Primer 6px. */
  --r: 6px;

  --sans: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  --mono: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace;
}

/* The viewer has THREE states, not two: an explicit choice stamps
   data-theme, and the default "system" setting stamps nothing. So the bare
   :root above is the complete light palette; the media query below redefines
   only the tokens and is guarded so an explicit light choice still beats a
   dark OS; and the [data-theme="dark"] block redefines them again so the
   toggle wins in the other direction. Defined twice, not the three times it
   was. */
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --ground: #161512; --panel: #262421; --sunk: #33312e;
    --ink: #bababa; --ink-soft: #949494; --ink-faint: #787878;
    --rule: #404040; --rule-strong: #5c5c5c;
    --accent: #3692e7; --accent-soft: #1f2d3a;
    --on-ink: #161512;
    --flag: #e8837b; --flag-soft: #3a1f1d; --info-soft: #1f2d3a;
  }
}
:root[data-theme="dark"] {
  --ground: #161512; --panel: #262421; --sunk: #33312e;
  --ink: #bababa; --ink-soft: #949494; --ink-faint: #787878;
  --rule: #404040; --rule-strong: #5c5c5c;
  --accent: #3692e7; --accent-soft: #1f2d3a;
  --on-ink: #161512;
  --flag: #e8837b; --flag-soft: #3a1f1d; --info-soft: #1f2d3a;
}
```

- [ ] **Step 2: Replace the move-list block and delete the legend block**

Replace `app.css` lines 144-159 (`#move-list` through `.legend .key + .key`)
with:

```css
/* Optimal -> Slower -> No mate is ONE ordinal axis, not three categories, so
   it is encoded by LUMINANCE AND WEIGHT with no hue at all: filled, then
   outlined, then faded and struck.

   This is syzygy's own device rather than an invention. It renders a
   five-level win / cursed-win / draw / blessed-loss / loss scale in white,
   mid-grey (#757575) and black -- the colours of the game itself, so it needs
   no legend -- and marks the two degraded levels with a 3px inset ring in the
   draw grey rather than a fourth hue. Its dark mode shifts that grey so the
   midpoint holds RELATIVE to the ground; ours does the same via --ink.

   Green -> amber -> red was the obvious move and is the wrong one: a slower
   move is not a warning. (Where lichess does use hue for move quality it runs
   blue -> amber -> red, holding green back for the exceptional case.) */

#move-list { display: flex; flex-direction: column; gap: var(--s3); margin: var(--s2) 0 0; }
.move-group { display: flex; flex-direction: column; gap: var(--s1); }
.move-group h3 { margin: 0; }
.move-group h3 .n { font-family: var(--mono); color: var(--ink-faint); font-weight: 400; }
.move-group ul { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 2px; }
.move-group li {
  display: flex; align-items: center; gap: var(--s2);
  padding: .4rem .55rem; border-radius: 4px; border: 1px solid transparent;
  cursor: pointer;
}
.move-group li:hover { border-color: var(--accent); }
.move-group li .san { font-family: var(--mono); font-size: var(--f2); font-weight: 600; min-width: 4.5em; }
.move-group li .badge {
  margin-left: auto; font-family: var(--mono); font-size: var(--f0);
  font-variant-numeric: tabular-nums; white-space: nowrap;
  padding: .2rem .45rem; border-radius: 3px;
}

/* top of the scale: solid, maximum contrast, and a bar in the gutter */
li.optimal { background: var(--sunk); box-shadow: inset 3px 0 0 var(--ink); }
li.optimal .badge { background: var(--ink); color: var(--on-ink); }
/* The qualifier is a RING, not a hue, so it survives greyscale and every form
   of colour blindness -- and the badge already says "only reply" in words. */
li.optimal.only .badge { box-shadow: inset 0 0 0 2px var(--on-ink); }

/* middle: outlined, same ink, no fill */
li.slower .san { font-weight: 400; }
li.slower .badge { color: var(--ink-soft); border: 1px solid var(--rule); }

/* bottom: faded and struck through */
li.dead .san {
  color: var(--ink-faint); font-weight: 400;
  text-decoration: line-through; text-decoration-thickness: 1px;
}
li.dead .badge { color: var(--ink-faint); }
```

- [ ] **Step 3: Take the accent out of the charts**

The histograms are the other place the accent was doing semantic work. Replace
lines 207-215 (`.hist .bar` through `.chart-legend i.wtm`) with:

```css
.hist .bar { background: var(--sunk); border-radius: 2px; height: .72rem; overflow: hidden; }
/* Two luminance levels, not two hues -- black-to-move and white-to-move are
   the two sides of the game, the same reasoning as the move list above. The
   accent is reserved for links and focus. */
.hist .bar > i { display: block; height: 100%; background: var(--ink); min-width: 1px; }
.hist .bar.wtm > i { background: var(--ink-faint); }

.chart-legend { display: flex; gap: .9rem; flex-wrap: wrap; margin-top: var(--s2);
                font-size: var(--f0); color: var(--ink-soft); }
.chart-legend span { display: inline-flex; align-items: center; gap: var(--s1); }
.chart-legend i { width: .8rem; height: .55rem; border-radius: 2px; background: var(--ink); }
.chart-legend i.wtm { background: var(--ink-faint); }
```

- [ ] **Step 4: Sweep the ad-hoc font sizes onto the scale**

Mechanical, one-for-one. Apply every row; do not change any other property:

| current | token | rules |
|---|---|---|
| `.7rem` | `var(--f0)` | `.eyebrow`, `.tile .k` |
| `.74rem` | `var(--f0)` | `.chip` |
| `.76rem` | `var(--f0)` | (was `.chart-legend` — already done in Step 3) |
| `.78rem` | `var(--f1)` | `.hist .k`, `.hist .v`, `#mine-form label` |
| `.8rem` | `var(--f1)` | `.hint` |
| `.82rem` | `var(--f1)` | `#material-list li, #mine-results li, #material-samples li` |
| `.84rem` | `var(--f1)` | `#lines` |
| `.85rem` | `var(--f2)` | `.tagline`, `#fen-input`, `label.inline`, `#mine-form input` |
| `.86rem` | `var(--f2)` | `.primer` |
| `.88rem` | `var(--f2)` | `.help`, `.empty` |
| `.9rem` | `var(--f2)` | `.verdict`, `#error-banner` |
| `.95rem` | `var(--f3)` | `.tile .v` |
| `1.05rem` | `var(--f4)` | `.brand h1` |
| `1.15rem` | `var(--f4)` | `.stats-head h2` |

Also: replace every `border-radius: 4px` / `5px` / `6px` on a **panel or
form control** with `var(--r)`; leave the 2-4px radii on bars, keys and
badges alone (they are intentionally tighter than their container). Body
`font-size: 15px` is unchanged.

- [ ] **Step 5: Verify no token was orphaned**

```bash
taskset -c 0-3 bash -c '
css=src/packages/web/helpmate_web/static/css/app.css
# every var(--x) used must be declared on :root
for t in $(grep -o "var(--[a-z0-9-]*)" "$css" | sed "s/var(--\(.*\))/\1/" | sort -u); do
  grep -q -- "--$t:" "$css" || echo "UNDECLARED: --$t"
done
# and the old palette must be gone. The .legend pattern is anchored: an
# unanchored "\.legend" also matches .chart-legend, which stays.
grep -n "f7f5f0\|a4542a\|0d7a53\|--step\|^\.legend" "$css" && echo "STALE TOKENS REMAIN" || echo "clean"
'
```

Expected: no `UNDECLARED` lines, and `clean`.

- [ ] **Step 6: Run the suites — CSS must not move any assertion**

```bash
taskset -c 0-3 make jstest
taskset -c 0-3 python -m pytest src/packages/web/tests/ui -v
```

Expected: PASS, 20 UI tests. A failure here means a selector was renamed, not
a colour changed.

- [ ] **Step 7: Look at it, in both themes**

```bash
taskset -c 0-3 python - <<'PY'
import os, subprocess, sys, tempfile, time, urllib.request, socket, helpmate
from playwright.sync_api import sync_playwright
d = tempfile.mkdtemp(prefix="helpmate-shot-")
helpmate.generate("KQvk", tables=d, threads=2)
s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
p = subprocess.Popen([sys.executable, "-m", "uvicorn", "--factory",
     "helpmate_server.main:_app_for_tests", "--port", str(port)],
    env={**os.environ, "HELPMATE_TABLES": d})
url = f"http://127.0.0.1:{port}"
for _ in range(100):
    try: urllib.request.urlopen(f"{url}/v1/health", timeout=1); break
    except Exception: time.sleep(.1)
out = os.environ.get("SHOTS", "/tmp/claude-1000/shots"); os.makedirs(out, exist_ok=True)
with sync_playwright() as pw:
    b = pw.chromium.launch(args=["--no-sandbox"])
    for scheme in ("light", "dark"):
        for w, h, tag in ((1280, 900, "wide"), (420, 900, "narrow")):
            ctx = b.new_context(viewport={"width": w, "height": h}, color_scheme=scheme)
            pg = ctx.new_page()
            pg.goto(f"{url}/#fen=7k%2F8%2F5K2%2F8%2F8%2F8%2F8%2F6Q1%20w%20-%20-%200%201")
            pg.wait_for_selector("#move-list li")
            pg.screenshot(path=f"{out}/{scheme}-{tag}.png", full_page=True)
            ctx.close()
    b.close()
p.terminate(); p.wait()
print("wrote", out)
PY
```

Then **read the four PNGs** with the Read tool. Check specifically: the
optimal row's gutter bar and filled badge are legible on both grounds; the
"only reply" ring is visible; the struck-through dead rows are readable, not
invisible; no text sits on a same-theme-opposite ground. If dark mode is
unreadable, a colour is declared only inside a media block — that is the
classic bug this token structure exists to prevent.

- [ ] **Step 8: Commit**

```bash
git add src/packages/web/helpmate_web/static/css/app.css
git commit -m "style(web): adopt lichess's palette, encode the ordinal without hue

The warm-cream ground with a terracotta flag is replaced. Not for being warm
-- lichess is hue 37 too, and is the world's most-used chess UI -- but for
being saturated: 30-40% is a colour where 5-10% is a tint, and cream plus
terracotta is a signature that now reads as machine-generated.

Values are lichess's shipped theme. Two rules: grounds carry one hue at 5-10%
saturation, ink and rules are exactly achromatic. syzygy's dark mode already
IS this palette (five exact matches), so we become consistent with the nearest
neighbour tool. Its light mode is stock Bootstrap 3 and is not copied.

The accent is now blue and confined to links, focus and hover. Optimal /
Slower / No mate is one ranked axis, not three categories, so it is carried by
luminance and weight -- filled, outlined, faded -- and the histograms drop the
accent for two luminance levels for the same reason.

Palette defined twice (light on bare :root, dark under a guarded media query
and under [data-theme=dark]) rather than the three times it was. Type and
spacing scales replace fourteen ad-hoc rem values and the never-used --step.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Responsive two-pane shell, and reference material that gets out of the way

**Files:**
- Modify: `src/packages/web/helpmate_web/static/css/app.css` (the `explorer` section, ~lines 113-126 post-Task-3)
- Modify: `src/packages/web/helpmate_web/static/index.html:48-52` (help copy + id), `:86` (primer id)
- Modify: `src/packages/web/helpmate_web/static/js/explorer.js` (inside `render()`)
- Modify: `src/packages/web/tests/ui/test_dashboard.py`

**Interfaces:**
- Consumes: `START` (already defined at `explorer.js:14`).
- Produces: `#explorer-help` and `#primer` — elements toggled by `hidden`.

**The arithmetic behind the breakpoint.** The board is `min(88vw, 460px)` and
the side column has `min-width: 300px`, with a `2rem` (32px) gap and `1.25rem`
of `main` padding each side: `460 + 32 + 300 + 40 = 832`. So two columns need
about 840px, and anything narrower must stack. The breakpoint is **860px**.
Mobile is the default and two columns are the enhancement, matching the
benchmark's `min-width: 680px` direction (its number is smaller because its
list column is capped at 310px; ours carries histograms and needs width).

- [ ] **Step 1: Write the failing tests**

Append to `src/packages/web/tests/ui/test_dashboard.py`:

```python
def test_the_board_stays_put_while_the_answer_scrolls(page, server):
    # Syzygy's structural win, without its 310px cap: a long move list must
    # never drag the board off screen. No sticky headers, no scroll sync --
    # position: sticky on the board column, and only above the breakpoint.
    page.set_viewport_size({"width": 1280, "height": 700})
    page.goto(f"{server}/#fen={quote(THREE_GROUPS)}")   # 28 moves: taller than the viewport
    page.wait_for_selector("#move-list li")
    page.mouse.wheel(0, 600)
    page.wait_for_function("() => window.scrollY > 100")
    top_after = page.eval_on_selector(".board-col", "e => e.getBoundingClientRect().top")
    # Without sticky this is around -500 (scrolled off the top). With it, the
    # column parks at --s3 from the viewport top and stays there.
    assert top_after >= 0, f"the board column scrolled out of view (top={top_after})"


def test_below_the_breakpoint_the_columns_stack_and_nothing_is_hidden(page, server):
    page.set_viewport_size({"width": 420, "height": 900})
    page.goto(f"{server}/#fen={quote(THREE_GROUPS)}")
    page.wait_for_selector("#move-list li")
    board = page.eval_on_selector(".board-col", "e => e.getBoundingClientRect()")
    side = page.eval_on_selector(".side", "e => e.getBoundingClientRect()")
    assert side["top"] >= board["bottom"] - 1, "columns did not stack"
    # Nothing is hidden on a small screen -- hiding controls is a support burden.
    for sel in ("#palette", "#fen-form", "#move-list", "#btn-export-pgn"):
        assert page.is_visible(sel), f"{sel} disappeared at 420px"
    # And the page never scrolls sideways.
    assert page.evaluate(
        "document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1")


def test_reference_material_appears_only_on_the_landing_position(page, server):
    # The benchmark renders its About/Download copy only when the FEN is the
    # default: ask a real question and the explanatory copy vanishes. A
    # published tool explains itself to a newcomer, then gets out of the way.
    page.goto(server)
    page.wait_for_selector("#move-list li")
    assert page.is_visible("#primer")
    assert page.is_visible("#explorer-help")

    page.goto(f"{server}/#fen={quote(SATURATED)}")
    page.wait_for_selector("#move-list li")
    page.wait_for_function("() => document.getElementById('primer').hidden === true")
    assert not page.is_visible("#explorer-help")
```

- [ ] **Step 2: Run them to verify they fail**

```bash
taskset -c 0-3 python -m pytest src/packages/web/tests/ui/test_dashboard.py \
  -k "board_stays_put or below_the_breakpoint or reference_material" -v
```

Expected: FAIL — `#primer` does not exist, and `.board-col` is not sticky.

- [ ] **Step 3: Rewrite the explorer layout rules**

Replace the `/* ---------- explorer ---------- */` layout block (post-Task-3
lines ~113-126, `#panel-explorer` through `.palette`) with:

```css
/* ---------- explorer ---------- */

/* Mobile is the default; two columns are the enhancement. 460px board +
   32px gap + 300px minimum side + 40px of main padding = 832, so the two
   columns need ~840px and the breakpoint sits just above at 860. */
#panel-explorer { display: flex; flex-direction: column; gap: var(--s4); }
.board-col { display: flex; flex-direction: column; gap: var(--s3); }
#board { width: min(88vw, 460px); aspect-ratio: 1; }
.side { display: flex; flex-direction: column; gap: var(--s4); min-width: 0; }
.side > * { margin: 0; }

@media (min-width: 860px) {
  #panel-explorer {
    display: grid;
    grid-template-columns: min(460px, 40%) minmax(300px, 1fr);
    gap: var(--s4);
    align-items: start;
  }
  /* The board pane stays put and only the answer pane scrolls, so a long
     move list never drags the board out of view. No sticky headers, no
     scroll-sync JavaScript. */
  .board-col { position: sticky; top: var(--s3); }
}

.palette {
  display: flex; flex-direction: column; gap: var(--s2);
  border: 1px solid var(--rule); border-radius: var(--r);
  background: var(--panel); padding: var(--s2) var(--s3);
  width: min(88vw, 460px);
}
```

Note `#panel-explorer` keeps `display: flex` in the base rule, so the
`[hidden] { display: none !important }` regression guarded by
`test_only_the_active_panel_is_visible` still applies — `!important` beats
both the flex and the grid declaration.

- [ ] **Step 4: Give the two reference elements ids and fix the copy**

In `index.html`, replace the help paragraph (lines 48-52):

```html
      <p class="help" id="explorer-help">
        Drag a piece to play its move, or click one from the list. Moves are
        grouped: the ones that keep the shortest mate first, then those that
        take longer, then those that lead nowhere. The position lives in the
        address bar, so any link you copy reopens it.
      </p>
```

The old copy named a colour ("outlined in green") that no longer exists and
described an encoding that is now the group headers' job.

And on line 86, `<details class="primer">` → `<details class="primer" id="primer">`.

- [ ] **Step 5: Toggle them in `render()`**

In `explorer.js`, immediately after the `syncControls(fen)` call at the top of
`render()` (line ~63), insert:

```js
  // Reference material is for a newcomer meeting the landing position; once
  // the user has a position of their own it gets out of the way. The
  // benchmark does the same with its About/Download copy, and the reasoning
  // is the same: a published tool explains itself, then stops talking.
  const landing = fen === START;
  document.getElementById("explorer-help").hidden = !landing;
  document.getElementById("primer").hidden = !landing;
```

- [ ] **Step 6: Run the new tests, then the whole suite**

```bash
taskset -c 0-3 python -m pytest src/packages/web/tests/ui/test_dashboard.py \
  -k "board_stays_put or below_the_breakpoint or reference_material" -v
taskset -c 0-3 python -m pytest src/packages/web/tests/ui -v
```

Expected: PASS, 23 tests total.

- [ ] **Step 7: Commit**

```bash
git add src/packages/web/helpmate_web/static/css/app.css \
        src/packages/web/helpmate_web/static/index.html \
        src/packages/web/helpmate_web/static/js/explorer.js \
        src/packages/web/tests/ui/test_dashboard.py
git commit -m "feat(web): responsive two-pane shell, landing-only reference copy

There was not one width query in 242 lines of CSS. Now: mobile is the
default, two columns are the enhancement above 860px (460 board + 32 gap +
300 side + 40 padding = 832), and above the breakpoint the board column is
sticky so a 28-move list never drags the board off screen. Nothing is hidden
on a small screen -- hiding controls is a support burden.

The primer and the help paragraph now render only on the landing position, as
the benchmark does with its About copy. The help copy also stopped naming a
green outline that no longer exists; grouping says it instead.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: The dark-mode toggle

**Files:**
- Create: `src/packages/web/helpmate_web/static/js/lib/theme-mode.js`
- Create: `src/packages/web/helpmate_web/static/js/theme-toggle.js`
- Test: `src/packages/web/tests/js/theme-mode.test.js`
- Modify: `src/packages/web/helpmate_web/static/index.html` (head script, header control, module import)
- Modify: `src/packages/web/helpmate_web/static/css/app.css` (header layout)
- Modify: `src/packages/web/tests/ui/test_dashboard.py`

**Interfaces:**
- Consumes: the token structure from Task 3 — specifically that dark lives
  under `@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) }`
  and `:root[data-theme="dark"]`, which is what makes three states work.
- Produces:
  - `lib/theme-mode.js`: `THEME_KEY: "helpmate:theme"`, `THEME_MODES: string[]`,
    `normalizeMode(v) -> "system"|"light"|"dark"`, `nextMode(m) -> string`,
    `themeAttr(m) -> string|null`, `modeLabel(m) -> string`
  - `theme-toggle.js`: `initTheme() -> void`

**Why the CSS already supports this and nothing does.** `app.css` has defined
a complete dark palette under both `prefers-color-scheme` and `[data-theme]`
since it was written, and **nothing in the codebase has ever set
`data-theme`** — it is dead code. This task is the missing control.

- [ ] **Step 1: Write the failing unit test**

Create `src/packages/web/tests/js/theme-mode.test.js`:

```js
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
```

- [ ] **Step 2: Run it to verify it fails**

```bash
taskset -c 0-3 node --test src/packages/web/tests/js/theme-mode.test.js
```

Expected: FAIL — module not found.

- [ ] **Step 3: Write the pure module**

Create `src/packages/web/helpmate_web/static/js/lib/theme-mode.js`:

```js
// Three-state theme selection, pure so `node --test` covers it. The DOM and
// localStorage live in theme-toggle.js.
//
// Three states, not two, because the viewer's default is "follow the system"
// and that is NOT the same as "light": it means stamp no attribute and let
// prefers-color-scheme decide. app.css guards its dark media query with
// :root:not([data-theme="light"]) so an explicit light choice still beats a
// dark OS, and repeats the dark tokens under :root[data-theme="dark"] so the
// toggle wins in the other direction.

export const THEME_KEY = "helpmate:theme";
export const THEME_MODES = ["system", "light", "dark"];

// Anything unrecognised -- a value from an older build, another app on the
// same origin, a hand-edited devtools entry -- is system. A bogus value must
// never reach the document as a data-theme attribute.
export function normalizeMode(value) {
  return THEME_MODES.includes(value) ? value : "system";
}

export function nextMode(mode) {
  const i = THEME_MODES.indexOf(normalizeMode(mode));
  return THEME_MODES[(i + 1) % THEME_MODES.length];
}

// null means "remove the attribute", which is what makes "system" work.
export function themeAttr(mode) {
  const m = normalizeMode(mode);
  return m === "system" ? null : m;
}

// One button cycling three states is only unambiguous if it says which state
// it is in, so the label carries the mode rather than an icon.
export function modeLabel(mode) {
  return `Theme: ${normalizeMode(mode)}`;
}
```

- [ ] **Step 4: Run the unit test to verify it passes**

```bash
taskset -c 0-3 node --test src/packages/web/tests/js/theme-mode.test.js
```

Expected: PASS, 5 tests.

- [ ] **Step 5: Write the failing UI tests**

Append to `src/packages/web/tests/ui/test_dashboard.py`:

```python
def test_theme_toggle_cycles_all_three_states_and_persists(page, server):
    page.goto(server)
    page.wait_for_selector("#move-list li")
    assert page.get_attribute("#theme-toggle", "data-mode") == "system"
    assert page.evaluate(
        "document.documentElement.hasAttribute('data-theme')") is False
    assert page.inner_text("#theme-toggle") == "Theme: system"

    page.click("#theme-toggle")
    assert page.get_attribute("html", "data-theme") == "light"
    page.click("#theme-toggle")
    assert page.get_attribute("html", "data-theme") == "dark"
    assert page.inner_text("#theme-toggle") == "Theme: dark"

    # The choice survives a reload -- and is applied before first paint, so
    # a dark-mode user never gets a white flash.
    page.reload()
    page.wait_for_selector("#move-list li")
    assert page.get_attribute("html", "data-theme") == "dark"

    page.click("#theme-toggle")   # back round to system
    assert page.evaluate(
        "document.documentElement.hasAttribute('data-theme')") is False


def test_an_explicit_light_choice_beats_a_dark_operating_system(browser, server):
    # The three-state point: prefers-color-scheme is the DEFAULT, not the
    # authority. If the media query were unguarded, a dark OS would win and
    # the light setting would do nothing.
    ctx = browser.new_context(color_scheme="dark")
    pg = ctx.new_page()
    pg.goto(server)
    pg.wait_for_selector("#move-list li")
    dark_bg = pg.eval_on_selector("body", "e => getComputedStyle(e).backgroundColor")
    pg.click("#theme-toggle")   # -> light
    assert pg.get_attribute("html", "data-theme") == "light"
    light_bg = pg.eval_on_selector("body", "e => getComputedStyle(e).backgroundColor")
    assert light_bg != dark_bg, "explicit light did not override the dark OS"
    ctx.close()


def test_the_theme_toggle_is_not_treated_as_a_panel_button(page, server):
    # panels.js binds EVERY `nav button` as a panel switch and reads
    # btn.dataset.panel. A stray button inside <nav> would call
    # showPanel(undefined) on click and hide all three panels at once -- a
    # failure that looks like a blank page and has no other test guarding it.
    page.goto(server)
    page.wait_for_selector("#move-list li")
    assert page.eval_on_selector("#theme-toggle", "e => e.closest('nav') === null")
    page.click("#theme-toggle")
    assert page.is_visible("#panel-explorer")
```

- [ ] **Step 6: Run them to verify they fail**

```bash
taskset -c 0-3 python -m pytest src/packages/web/tests/ui/test_dashboard.py \
  -k "theme_toggle or explicit_light" -v
```

Expected: FAIL — `#theme-toggle` does not exist.

- [ ] **Step 7: Write the DOM wrapper**

Create `src/packages/web/helpmate_web/static/js/theme-toggle.js`:

```js
import {
  THEME_KEY, normalizeMode, nextMode, themeAttr, modeLabel,
} from "./lib/theme-mode.js";

// localStorage throws rather than returning null in some privacy modes and
// under a file:// origin. The toggle must still work for the session then --
// it just won't be remembered.
function readMode() {
  try { return normalizeMode(localStorage.getItem(THEME_KEY)); }
  catch { return "system"; }
}
function writeMode(mode) {
  try { localStorage.setItem(THEME_KEY, mode); }
  catch { /* not remembered; the page still honours the click */ }
}

function apply(mode) {
  const attr = themeAttr(mode);
  if (attr === null) document.documentElement.removeAttribute("data-theme");
  else document.documentElement.setAttribute("data-theme", attr);
  const btn = document.getElementById("theme-toggle");
  btn.textContent = modeLabel(mode);
  btn.dataset.mode = mode;
}

export function initTheme() {
  let mode = readMode();
  apply(mode);
  document.getElementById("theme-toggle").addEventListener("click", () => {
    mode = nextMode(mode);
    writeMode(mode);
    apply(mode);
  });
}
```

- [ ] **Step 8: Add the control, the head script, and the import**

In `index.html`, inside `<head>` after the stylesheet links, add:

```html
<script>
  // Applied before first paint, so a dark-mode user reloading the page never
  // sees a white flash. This is the ONE place theme-mode.js's logic is
  // duplicated; it is deliberate (a module import cannot run before the CSS
  // paints) and must stay in sync with normalizeMode/themeAttr.
  try {
    var m = localStorage.getItem("helpmate:theme");
    if (m === "light" || m === "dark") document.documentElement.setAttribute("data-theme", m);
  } catch (e) { /* storage unavailable: fall back to prefers-color-scheme */ }
</script>
```

Replace the header's chip line (line 22) with:

```html
  <div class="header-end">
    <button type="button" id="theme-toggle" data-mode="system">Theme: system</button>
    <span id="server-chip" class="chip" hidden></span>
  </div>
```

**The button must stay outside `<nav>`** — `panels.js` binds every `nav
button` as a panel switch and reads `btn.dataset.panel`, so a stray button
there would call `showPanel(undefined)` and hide all three panels.

Extend the module block at the bottom:

```html
<script type="module">
  import { initPanels } from "/js/panels.js";
  import { initExplorer } from "/js/explorer.js";
  import { initMaterials } from "/js/materials.js";
  import { initMine } from "/js/mine.js";
  import { initServerChip } from "/js/chip.js";
  import { initTheme } from "/js/theme-toggle.js";
  initTheme();
  initPanels(); initExplorer(); initMaterials(); initMine(); initServerChip();
</script>
```

- [ ] **Step 9: Style the header end**

In `app.css`, replace the `.chip` rule's `margin-left: auto` with a wrapper
rule (the chip no longer positions itself):

```css
.header-end { margin-left: auto; display: flex; align-items: center; gap: var(--s2); }
#theme-toggle { font-size: var(--f0); color: var(--ink-soft); }
#theme-toggle:hover { color: var(--ink); }
.chip {
  font-family: var(--mono); font-size: var(--f0);
  color: var(--ink-soft); border: 1px solid var(--rule);
  border-radius: 999px; padding: .15rem .65rem; white-space: nowrap;
}
.chip.down { color: var(--flag); border-color: var(--flag); }
```

- [ ] **Step 10: Run the new tests, then everything**

```bash
taskset -c 0-3 python -m pytest src/packages/web/tests/ui/test_dashboard.py \
  -k "theme_toggle or explicit_light" -v
taskset -c 0-3 make jstest
taskset -c 0-3 python -m pytest src/packages/web/tests/ui -v
```

Expected: PASS, 26 UI tests.

- [ ] **Step 11: Commit**

```bash
git add src/packages/web/helpmate_web/static/js/lib/theme-mode.js \
        src/packages/web/helpmate_web/static/js/theme-toggle.js \
        src/packages/web/tests/js/theme-mode.test.js \
        src/packages/web/helpmate_web/static/index.html \
        src/packages/web/helpmate_web/static/css/app.css \
        src/packages/web/tests/ui/test_dashboard.py
git commit -m "feat(web): a real dark-mode toggle

app.css has carried a complete dark palette under both prefers-color-scheme
and [data-theme] since it was written, and nothing in the codebase has ever
set data-theme. This is the missing control.

Three states, not two: system means stamp no attribute and let
prefers-color-scheme decide, which is why an explicit light choice still has
to beat a dark OS -- guarded in the CSS, asserted in a test that runs the
context with color_scheme=dark. One button that names its own state, so
cycling three ways is unambiguous. A five-line head script applies the stored
choice before first paint; that duplication is deliberate and labelled.

The button is deliberately outside <nav>: panels.js binds every nav button as
a panel switch, so a stray one would call showPanel(undefined) and blank the
page. Guarded by its own test.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Search and materials — the same treatment, no new capability

**Files:**
- Modify: `src/packages/web/helpmate_web/static/js/mine.js:61-66` (result rows)
- Modify: `src/packages/web/helpmate_web/static/css/app.css` (the search section)
- Modify: `src/packages/web/tests/ui/test_dashboard.py`

**Interfaces:**
- Consumes: the tokens from Task 3.
- Produces: nothing new. `#mine-results li` stays the selector.

**A deliberate narrowing of the spec, stated plainly.** The spec asks for
search results "presented as a table with the data we already have rather than
a flat list of FEN strings". Checked against the actual payload: `/v1/mine`
returns `{fens, truncated, skipped_saturated}` and nothing per-row. Every
column a table could add — material, dtm, count, side to move — is a
**constant of the query**, identical in all 50 rows, and deriving side-to-move
from the FEN adds a column whose parity is fixed by `dtm`. A table of constant
columns is worse than a list, and converting `#mine-results` from `<ul>` to
`<table>` would break two passing UI tests for no gain.

So: the list stays a list, and gets the part of the ask that is real — a row
index so a result is nameable, monospace alignment, and the token system.
**If the user wants genuine per-row data here, that needs `/v1/mine` to return
values alongside the FENs, which is an API change and its own cycle.**

- [ ] **Step 1: Write the failing test**

Append to `src/packages/web/tests/ui/test_dashboard.py`:

```python
def test_search_results_are_numbered_and_open_in_the_explorer(page, server):
    page.goto(f"{server}/#panel=mine")
    page.fill("#mine-form input[name=material]", "KQvk")
    page.fill("#mine-form input[name=dtm]", "2")
    page.click("#mine-form button[type=submit]")
    page.wait_for_selector("#mine-results li")
    idx = page.eval_on_selector_all("#mine-results li .idx",
                                    "els => els.map(e => e.textContent)")
    assert idx[:3] == ["1", "2", "3"], idx[:3]
    assert len(idx) == page.eval_on_selector_all("#mine-results li", "els => els.length")
    # each row still carries its FEN and still navigates
    first = page.eval_on_selector("#mine-results li .fen", "e => e.textContent")
    assert first.count("/") == 7
    page.click("#mine-results li")
    page.wait_for_selector("#panel-explorer:not([hidden])")
    # The click sets location.hash; panels.js and explorer.js both react to
    # hashchange, and explorer's render() is async -- so wait for the value
    # rather than reading it in the same tick.
    page.wait_for_function(
        "want => document.getElementById('fen-input').value === want", arg=first)
```

- [ ] **Step 2: Run it to verify it fails**

```bash
taskset -c 0-3 python -m pytest src/packages/web/tests/ui/test_dashboard.py \
  -k "search_results_are_numbered" -v
```

Expected: FAIL — `#mine-results li .idx` never matches.

- [ ] **Step 3: Render the rows with an index**

In `mine.js`, replace lines 61-66 with:

```js
  b.fens.forEach((fen, i) => {
    const li = document.createElement("li");
    const idx = document.createElement("span");
    idx.className = "idx";
    idx.textContent = i + 1;
    const text = document.createElement("span");
    text.className = "fen";
    text.textContent = fen;
    li.append(idx, text);
    li.addEventListener("click", () => { location.hash = encodeState({ fen, panel: "explorer" }); });
    results.appendChild(li);
  });
```

- [ ] **Step 4: Style the rows**

Append to the search section of `app.css`:

```css
#mine-results li { display: flex; align-items: baseline; gap: var(--s2); }
#mine-results li .idx {
  color: var(--ink-faint); font-variant-numeric: tabular-nums;
  min-width: 2.5ch; text-align: right; flex: none;
}
#mine-results li .fen { overflow-wrap: anywhere; }
```

- [ ] **Step 5: Check every panel for stale accent use**

The accent is now reserved for links, focus and hover. Grep for it and confirm
each remaining use is one of those three:

```bash
taskset -c 0-3 grep -n "var(--accent" src/packages/web/helpmate_web/static/css/app.css
```

Convert any use that is a **selection fill or a chart series** to
`--sunk` + `--rule-strong` (selected) or `--ink` / `--ink-faint` (series).
Specifically expected to need changing:
`#material-list li[aria-selected="true"]` and
`.palette button[aria-pressed="true"]` — a pressed/selected state is not a
link. Use:

```css
#material-list li[aria-selected="true"] { border-color: var(--rule-strong); background: var(--sunk); font-weight: 600; }
.palette button[aria-pressed="true"] { border-color: var(--rule-strong); background: var(--sunk); font-weight: 600; }
```

Keep `:focus-visible { outline: 2px solid var(--accent) }` and the `:hover`
border rules — those are exactly the licensed uses.

- [ ] **Step 6: Run everything**

```bash
taskset -c 0-3 make jstest
taskset -c 0-3 python -m pytest src/packages/web/tests/ui -v
```

Expected: PASS, 27 UI tests. Note that
`test_the_palette_places_a_piece_and_evaluates_on_exit` asserts on
`aria-pressed`, not on colour, so the palette restyle above cannot break it.

- [ ] **Step 7: Commit**

```bash
git add src/packages/web/helpmate_web/static/js/mine.js \
        src/packages/web/helpmate_web/static/css/app.css \
        src/packages/web/tests/ui/test_dashboard.py
git commit -m "feat(web): number the search results, finish the accent discipline

The spec asked for search results as a table. Checked against the payload:
/v1/mine returns {fens, truncated, skipped_saturated} and nothing per-row, so
every column a table could add -- material, dtm, count, side to move -- is a
constant of the query, identical in all 50 rows. A table of constant columns
is worse than a list, and the conversion would break two passing tests for no
gain. Genuine per-row data needs /v1/mine to return values alongside the
FENs, which is an API change and its own cycle.

So the list stays a list and gets the real part of the ask: a row index, so a
result is nameable, and monospace alignment.

Also finishes Task 3's rule that the accent means links, focus and hover and
nothing else -- selected/pressed states move to the neutral ramp.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: Full gate, docs, and a look at the result

**Files:**
- Modify: `docs/USAGE.md:1320` (the green-outline sentence) and the Search bullet
- Modify: `docs/superpowers/specs/2026-08-09-dashboard-redesign-design.md` (record the Task 6 narrowing)

- [ ] **Step 1: Run every gate the repo has**

```bash
taskset -c 0-3 make lint
taskset -c 0-3 make jstest
taskset -c 0-3 python -m pytest src/packages/web/tests/ui -v
taskset -c 0-3 python -m pytest src/packages/api/tests -v
taskset -c 0-3 python -m pytest tests/repo -v
taskset -c 0-3 make typecheck
```

Expected: all pass. `make format-check` is not needed — this plan touches no
C++ — but run it if any `.cpp`/`.h` file appears in `git status`.

Do **not** report a gate as passing without pasting its actual last line into
the task notes. If something fails, fix it; if it was already failing on
`main`, say so with the evidence (`git stash && <command>`) rather than
assuming.

- [ ] **Step 2: Fix the docs that describe the old UI**

`docs/USAGE.md:1320` currently reads "…which shows the value each move leads
to and outlines in green the ones that keep the shortest mate." Replace the
Explorer bullet's first sentences with:

```markdown
- **Explorer** — an interactive board. Drag a piece to play its move, or click
  one from the complete legal-move list, which is grouped into **Optimal**
  (keeps the shortest mate), **Slower** and **No mate**, with the optimal
  moves ordered by how forcing they are — the child position's optimal-line
  count, ascending, since mate length is constant across that group by
  construction. A saturated count renders as `255+`, never `255`. Below it, the
```

And add to the Search bullet, after "exportable as a FEN list or CSV":

```markdown
  Results are numbered so a row is nameable.
```

Then grep for anything else that describes the old look:

```bash
taskset -c 0-3 grep -rn "green\|legend\|outlines" docs/*.md README.md | grep -iv "keep green"
```

Fix whatever that finds.

- [ ] **Step 3: Record the Task 6 narrowing in the spec**

Append to the "Search panel" section of
`docs/superpowers/specs/2026-08-09-dashboard-redesign-design.md`:

```markdown
**Amended during implementation (2026-08-11).** "Results presented as a table"
was not built. `/v1/mine` returns `{fens, truncated, skipped_saturated}` and
nothing per-row, so every column a table could carry — material, dtm, count,
side to move — is a constant of the query, identical in every row. A table of
constant columns is worse than a list, and the conversion would have broken
two passing UI tests for no gain. The list keeps its `<ul>` and gains a row
index. Genuine per-row data requires `/v1/mine` to return values alongside the
FENs; that is an API change and belongs to its own cycle.
```

- [ ] **Step 4: Look at the finished thing, in both themes and both widths**

Re-run the screenshot script from Task 3 Step 7, and additionally capture the
landing position (`{url}/` with no hash) and the search panel
(`{url}/#panel=mine`). **Read every PNG.** Check:

- the optimal row leads, with its gutter bar and filled badge;
- `255+` appears on the saturated fixture and bare `255` appears nowhere;
- dark mode is legible everywhere — especially the struck-through dead rows
  and the histogram bars;
- at 420px nothing is cut off and the page does not scroll sideways;
- the primer is present on the landing position and gone on any other.

- [ ] **Step 5: Commit and open the PR**

```bash
git add docs/USAGE.md docs/superpowers/specs/2026-08-09-dashboard-redesign-design.md
git commit -m "docs: describe the redesigned dashboard

USAGE still told the reader that optimal moves are 'outlined in green'. They
are grouped under a header that says so in words, and the accent is no longer
green or used on the move list at all.

Also records the one place implementation narrowed the spec: search results
stay a list, because every column a table could add is a constant of the query.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

Then push and open the PR. `origin` is an SSH URL and the user's gitconfig
rewrites HTTPS→SSH, which hangs on an invisible passphrase dialog, so both
commands need the explicit HTTPS URL and the `gh` credential helper:

```bash
GIT_CONFIG_GLOBAL=/dev/null git -c credential.helper='!gh auth git-credential' \
  push https://github.com/osick/8pieces-helpmate.git HEAD:feat/dashboard-redesign
gh pr create --base main --head feat/dashboard-redesign \
  --title "Professionalize the dashboard for public release" \
  --body "$(cat <<'EOF'
Implements `docs/superpowers/specs/2026-08-09-dashboard-redesign-design.md`.

**The move list is the centre of it.** Rows rendered in move-generator order
meant the only move keeping the shortest mate could sit fourth, under three
that throw a move away. Now: Optimal / Slower / No mate, counted headers, row
one is always the answer. Inside the optimal group the sort key is the child's
solution count ascending — mate length is constant there by construction, so
it cannot order anything, while the count says how forcing the move is. A
saturated count renders `255+`, never `255`.

**The palette is lichess's**, read off its shipped theme: grounds carry one
hue at 5–10% saturation, ink and rules are exactly achromatic, and the single
accent is blue and confined to links, focus and hover. syzygy's dark mode
already *is* this palette, so we are now consistent with the nearest
neighbour tool rather than merely inspired by it.

**The ordinal carries no hue.** Optimal → Slower → No mate is one ranked axis,
so it is encoded by luminance and weight — filled, outlined, faded and struck
— which is syzygy's own device for its five-level WDL scale.

Plus: a responsive two-pane shell with a sticky board above 860px, reference
copy that appears only on the landing position, and a three-state dark-mode
toggle for a palette that had been dead code since it was written.

All 16 pre-existing UI tests pass **unedited**; 11 new UI cases and 14 new JS
unit cases were added.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Self-review

**Spec coverage.** Every section of the design doc maps to a task:

| spec section | task |
|---|---|
| Move list — grouping, sort keys, badges | 1, 2 |
| `count` means the child's count; `255+` never `255` | 1 (unit), 2 (UI) |
| DOM contract preserved, `#move-list li` unchanged | 2 |
| Layout — fixed board, scrolling answer, fluid grid, stacking, nothing hidden | 4 |
| Reference material only on the empty board | 4 |
| Design tokens — type scale, spacing scale, one palette | 3 |
| Palette replaced (lichess), ordinal without hue | 3 |
| Dark mode gets a toggle (three-state) | 5 |
| Search panel — design system, no new capability | 6 |
| 38 JS unit tests stay green untouched | verified in 1, 5, 7 |
| 16 Playwright tests are the contract | verified in 2, 4, 5, 6, 7 |
| New tests required for the sort | 2 |
| Non-goals: no build step, no framework, no npm, no new endpoints | Global Constraints |

One spec line is **not** implemented as written — search results as a table —
and Task 6 states why, changes the spec to match, and names what would be
needed to do it properly.

**Type consistency.** `groupMoves` / `waysLabel` / `moveBadge` / `moveClass`
are defined in Task 1 and used under exactly those names in Task 2.
`normalizeMode` / `nextMode` / `themeAttr` / `modeLabel` / `THEME_KEY` are
defined in Task 5 Step 3 and used under those names in Step 7. The group keys
`optimal` / `slower` / `dead` are the same string in `moveClass`, in
`data-group`, and in every CSS selector and test selector.

**Known risk, called out rather than discovered later.** The fixture values in
Tasks 1 and 2 were measured against `~/tb/KQvk.hm`, while the tests run
against a KQvk table generated fresh by `conftest.py`. Generation is
deterministic so they must agree — but Task 2 Step 5 is what proves it. If a
count differs, **the fixture table is the authority**: re-probe it and update
the plan's numbers, never loosen the assertion.
