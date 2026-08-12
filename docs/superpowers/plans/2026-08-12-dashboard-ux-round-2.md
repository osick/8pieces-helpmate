# Dashboard UX Round 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove every editing mode from the board — drag is always live, drag off the board deletes — and stop the readout repeating itself, so the explorer says each shared fact once.

**Architecture:** The two board input handlers merge into one: a drag that matches a legal move plays it, any other drag relocates the piece, and a drag off the board deletes it. That deletes the four-way arming, three buttons and the `commitBoard`/`editBaseline` machinery. In the readout, `lib/moves.js` gains distance **bands**, and groups whose per-move badge carries nothing unique render as chips instead of rows.

**Tech Stack:** Vanilla ES modules served from site-packages, cm-chessboard 8.7.5 (vendored, MIT), FastAPI, pytest, Playwright, `node --test`. No build step.

**Spec:** `docs/superpowers/specs/2026-08-12-dashboard-ux-round-2-design.md`

## Global Constraints

- **Every build/test command runs under `taskset -c 0-3`.** Never more cores.
- **Never write to `~/tb` or `~/tb/raw`** — a generation run is live there. Reading is fine.
- **Never `rm -rf /tmp/tmp.*`** (shared temp dir).
- Prefix pip/build commands with `GIT_CONFIG_GLOBAL=/dev/null` — the gitconfig rewrites HTTPS to SSH and a stray fetch hangs on an invisible passphrase prompt.
- **No new colours.** `tests/repo/test_accent_confined_to_focus_and_hover.py` requires every `var(--accent` inside a `:focus-visible` or `:hover` selector.
- `js/lib/` is the pure, node-unit-tested layer: no DOM APIs, no network.
- **`#move-list li` must keep selecting exactly the legal-move entries** — chips are `<li>` inside the group's `<ul>` and keep `data-san`. Several tests count it.
- `.rail` + inner pin wrapper + `.readout` is the panel structure; `position: sticky` stays on the pin, never the rail, or a colour seam returns below it.
- **Always use the make targets** (`make test-web`, `make test-api`) — they reinstall first, and the fixtures serve the *installed* package.
- `make lint` runs `node --check` over `git ls-files --cached --others --exclude-standard`; keep Python test imports at the top of the file (ruff E402).
- Commit trailer, exactly: `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`

## File Structure

**Modify**

| File | Change |
|---|---|
| `static/js/lib/moves.js` | distance bands; `moveBadge` loses the slower/dead cases |
| `static/js/explorer.js` | one merged board handler; delete arming, `commitBoard`, `editBaseline`, `onSquareClick`, palette click binding; chip renderer |
| `static/index.html` | trays above/below the board; palette panel, hint and `Set` removed; one-line controls |
| `static/css/app.css` | tray placement, chips, weight rule, one-line table band; armed-ring and `.palette` panel rules removed |
| `static/js/stats-view.js` | a one-line summary renderer for the explorer band |
| `tests/js/moves.test.js` | band tests |
| `tests/ui/test_dashboard.py` | rewrite the editor tests against the new model |
| `README.md`, `docs/USAGE.md`, `CHANGELOG.md`, `VERSION`, 4 × version sites | docs + 0.12.0 |

---

### Task 1: Distance bands in the move grouper

**Files:**
- Modify: `src/packages/web/helpmate_web/static/js/lib/moves.js`
- Test: `src/packages/web/tests/js/moves.test.js`

**Interfaces:**
- Produces: `groupMoves(moves)` now returns `[{ key, label, moves, bands }]`, where `bands` is `null` for the optimal group and otherwise `[{ label: string|null, moves: [...] }]`. Task 4 renders it.

- [ ] **Step 1: Write the failing tests**

Append to `src/packages/web/tests/js/moves.test.js`:

```js
const M = (san, dtm, count, opts = {}) => ({
  san, dtm, count,
  solvable: opts.solvable !== false,
  optimal: opts.optimal === true,
  notation: opts.notation ?? (dtm == null ? null : `h#${dtm / 2}`),
  uci: opts.uci ?? san.toLowerCase(),
  fen: opts.fen ?? `fen-${san}`,
});

test("the optimal group is never banded — its per-move count is the datum", () => {
  const g = groupMoves([M("Kh8", 1, 1, { optimal: true }), M("Kh6", 1, 3, { optimal: true })]);
  const optimal = g.find((x) => x.key === "optimal");
  assert.equal(optimal.bands, null);
  assert.deepEqual(optimal.moves.map((m) => m.san), ["Kh8", "Kh6"]);
});

test("slower moves band by distance, in distance order", () => {
  const g = groupMoves([
    M("Qg5", 4, 2), M("Qa7", 2, 9), M("Kf7", 2, 1), M("Ke5", 4, 1),
  ]);
  const slower = g.find((x) => x.key === "slower");
  assert.deepEqual(slower.bands.map((b) => b.label), ["h#1", "h#2"]);
  assert.deepEqual(slower.bands[0].moves.map((m) => m.san), ["Kf7", "Qa7"]);
  assert.deepEqual(slower.bands[1].moves.map((m) => m.san), ["Ke5", "Qg5"]);
});

test("a slower group with one distance still renders exactly one band", () => {
  const g = groupMoves([M("Qa7", 2, 1), M("Qg2", 2, 4)]);
  const slower = g.find((x) => x.key === "slower");
  assert.equal(slower.bands.length, 1);
  assert.equal(slower.bands[0].label, "h#1");
});

test("no-mate moves form one unlabelled band — nothing differs between them", () => {
  const g = groupMoves([M("Qg8", null, 0, { solvable: false }), M("Qg6", null, 0, { solvable: false })]);
  const dead = g.find((x) => x.key === "dead");
  assert.equal(dead.bands.length, 1);
  assert.equal(dead.bands[0].label, null);
  assert.deepEqual(dead.bands[0].moves.map((m) => m.san), ["Qg6", "Qg8"]);
});

test("every banded move appears exactly once across the bands", () => {
  const moves = [M("Qg5", 4, 2), M("Qa7", 2, 9), M("Kf7", 2, 1), M("Ke5", 6, 1)];
  const slower = groupMoves(moves).find((x) => x.key === "slower");
  const flat = slower.bands.flatMap((b) => b.moves.map((m) => m.san)).sort();
  assert.deepEqual(flat, ["Ke5", "Kf7", "Qa7", "Qg5"]);
  assert.equal(flat.length, slower.moves.length);
});
```

- [ ] **Step 2: Run to verify they fail**

Run: `taskset -c 0-3 make jstest`
Expected: FAIL — `bands` is `undefined`.
`make jstest` uses node's **spec** reporter: a failure is a `✖` line and a non-zero exit code. Do not grep for `not ok`.

- [ ] **Step 3: Implement**

In `src/packages/web/helpmate_web/static/js/lib/moves.js`, add to each `GROUPS` entry a `banded` flag and a band-label function, then build the bands in `groupMoves`. Replace the `GROUPS` array's three entries' trailing properties and `groupMoves` with:

```js
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
    // Never banded: the per-move count is exactly what this group exists to
    // show, so its rows keep their badges.
    band: null,
  },
  {
    key: "slower",
    label: "Slower",
    holds: (m) => m.solvable === true && m.optimal !== true,
    order: (a, b) => (a.dtm - b.dtm) || (a.count - b.count) || bySan(a, b),
    // Within one distance every move's badge would read the same, so the
    // distance becomes the band label and the badge disappears.
    band: (m) => m.notation,
  },
  {
    key: "dead",
    label: "No mate",
    holds: (m) => m.solvable !== true,
    // Every move here has dtm null, so it must never reach a numeric
    // comparator: null - null is 0, which would silently degrade to input
    // order rather than failing loudly.
    order: bySan,
    // Nothing distinguishes one dead move from another: one unlabelled band.
    band: () => null,
  },
];

// Non-empty groups, in fixed order. `filter` copies, so the caller's array is
// never reordered -- the drag-to-play path in explorer.js reads the same
// array and relies on it being untouched.
//
// `bands` is null for a group whose rows carry their own badge, and otherwise
// the group's moves split by band label, IN THE GROUP'S OWN ORDER -- the
// comparator already sorts by distance first, so walking the sorted list and
// starting a new band whenever the label changes yields distance order
// without a second sort.
export function groupMoves(moves) {
  const out = [];
  for (const g of GROUPS) {
    const rows = (moves || []).filter(g.holds).sort(g.order);
    if (!rows.length) continue;
    let bands = null;
    if (g.band) {
      bands = [];
      for (const m of rows) {
        const label = g.band(m);
        const last = bands[bands.length - 1];
        if (last && last.label === label) last.moves.push(m);
        else bands.push({ label, moves: [m] });
      }
    }
    out.push({ key: g.key, label: g.label, moves: rows, bands });
  }
  return out;
}
```

- [ ] **Step 4: Run to verify they pass**

Run: `taskset -c 0-3 make jstest`
Expected: PASS, exit 0.

- [ ] **Step 5: Prove the banding is not decorative**

Temporarily change the slower group's `band` to `() => null` (one band for everything), run `taskset -c 0-3 make jstest`, and confirm the distance-band tests FAIL. Restore and confirm they pass. Record both runs' output — a band that cannot be seen to fail is not evidence of anything.

- [ ] **Step 6: Commit**

```bash
git add src/packages/web/helpmate_web/static/js/lib/moves.js \
        src/packages/web/tests/js/moves.test.js
git commit -m "feat(web): band the slower and no-mate groups by distance

Within one distance every slower move's badge reads the same string, so
the distance becomes the band label and the badge stops being repeated.
The optimal group is never banded: its per-move solution count is the one
thing the list exists to show.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: The board has no modes

**Files:**
- Modify: `src/packages/web/helpmate_web/static/js/explorer.js:324-520` (editor + input), `:581-640` (init)
- Modify: `src/packages/web/helpmate_web/static/index.html` (palette panel)
- Modify: `src/packages/web/helpmate_web/static/css/app.css` (armed ring, palette panel)
- Test: `src/packages/web/tests/ui/test_dashboard.py`

**Interfaces:**
- Consumes: `squareFromTarget`, `exceedsDragThreshold` from `js/lib/board-edit.js` (unchanged).
- Produces: no exported interface; the board is operated entirely by drag.

**What is deleted:** `ARRANGE`, `armed`, `editBaseline`, `setArmed`, `commitBoard`, `onSquareClick`, `enableDragToEdit`, `enableDragToPlay` (merged), the palette `click` binding, the `btn.dataset.dragged` suppression, `#btn-erase`, `#btn-arrange`, `#btn-done-editing`, `#edit-hint`, the `Edit position` eyebrow, and the `.palette button[aria-pressed="true"]` rule.

**What is kept:** `#btn-clear-board`, the promotion dialog path, `kingProblem`'s no-request short circuit, and the palette-drag pointer machinery (minus its arming call).

- [ ] **Step 1: Write the failing tests**

In `src/packages/web/tests/ui/test_dashboard.py`, **replace** `test_the_palette_places_a_piece_and_evaluates_on_exit`, `test_done_evaluates_and_leaves_edit_mode`, `test_done_puts_the_edited_position_in_the_url_and_back_undoes_it`, `test_arming_and_disarming_without_editing_pushes_no_history` and `test_a_cancelled_drag_does_not_swallow_the_next_tap` with the following. (The last two go entirely: there is no arming to be a no-op, and no click handler for a stuck flag to swallow.)

```python
def _square_box(page, square):
    return page.locator(f"#board rect[data-square={square}]").bounding_box()


def _drag_square_to_square(page, frm, to):
    a, b = _square_box(page, frm), _square_box(page, to)
    page.mouse.move(a["x"] + a["width"] / 2, a["y"] + a["height"] / 2)
    page.mouse.down()
    page.mouse.move(b["x"] + b["width"] / 2, b["y"] + b["height"] / 2, steps=10)
    page.mouse.up()


def test_a_legal_drag_plays_the_move(page, server):
    # 8/7k/5K2/8/8/8/8/6Q1 b: Black to move, Kh7 may go to h8.
    page.goto(server)
    page.wait_for_selector("#move-list li")
    assert page.eval_on_selector("#stm-select", "e => e.value") == "b"
    _drag_square_to_square(page, "h7", "h8")
    page.wait_for_function(
        "() => document.getElementById('stm-select').value === 'w'")
    assert "8/7k" not in page.input_value("#fen-input")
    assert "dtm" in page.inner_text("#position-summary")


def test_an_illegal_drag_relocates_and_keeps_the_side_to_move(page, server):
    # The white queen cannot legally move at all here -- it is Black's turn --
    # so dragging it is unambiguously a relocation.
    page.goto(server)
    page.wait_for_selector("#move-list li")
    _drag_square_to_square(page, "g1", "d4")
    page.wait_for_function(
        "() => document.getElementById('fen-input').value.startsWith('8/7k/5K2/8/3Q4/')")
    assert page.eval_on_selector("#stm-select", "e => e.value") == "b", "a relocation flipped the turn"
    page.wait_for_function(
        "() => document.getElementById('position-summary').textContent.includes('dtm')")


def test_back_undoes_a_relocation(page, server):
    page.goto(server)
    page.wait_for_selector("#move-list li")
    before = page.input_value("#fen-input")
    _drag_square_to_square(page, "g1", "d4")
    page.wait_for_function(
        "b => document.getElementById('fen-input').value !== b", arg=before)
    page.click("#btn-back")
    page.wait_for_function(
        "b => document.getElementById('fen-input').value === b", arg=before)


def test_a_relocation_reaches_the_url(page, server):
    page.goto(server)
    page.wait_for_selector("#move-list li")
    _drag_square_to_square(page, "g1", "d4")
    page.wait_for_function("() => location.hash.includes('3Q4')")


def test_the_board_has_no_mode_controls(page, server):
    page.goto(server)
    page.wait_for_selector("#move-list li")
    for gone in ("#btn-erase", "#btn-arrange", "#btn-done-editing", "#edit-hint"):
        assert page.eval_on_selector_all(gone, "e => e.length") == 0, f"{gone} still exists"
    # and a tray piece is draggable without arming anything first
    assert page.eval_on_selector_all(
        "#palette-pieces button[aria-pressed]", "e => e.length") == 0
```

Also **simplify** `test_dragging_a_piece_off_the_board_removes_it` — delete its `page.click("#btn-arrange")` line and the `aria-pressed` assertion; the drag must now work with no preparation. And **simplify** `test_dragging_a_piece_from_the_palette_places_it` — delete its `#btn-done-editing` assertion and instead assert the position evaluates immediately (`#position-summary` contains `dtm`, or names the missing king).

- [ ] **Step 2: Run to verify they fail**

Run: `taskset -c 0-3 make test-web`
Expected: the five new tests fail; `test_the_board_has_no_mode_controls` fails because the buttons still exist.

- [ ] **Step 3: Merge the two board handlers**

In `explorer.js`, delete `commitBoard`, `onSquareClick`, `setArmed`, `enableDragToEdit` and `enableDragToPlay`, delete the `ARRANGE`, `armed` and `editBaseline` declarations, and add this single handler in their place:

```js
// ---- board input -----------------------------------------------------

// One rule, no modes. A drag whose from/to matches a legal move plays it; any
// other drag relocates the piece; a drag off the board deletes it. Editing is
// never gated behind a control, which is what lets three buttons and the whole
// armed-state machinery go.
//
// `playedMove` exists because BOTH outcomes travel through the same event
// pair: validateMoveInput decides, moveInputFinished fires afterwards either
// way. Without the flag, a legal move would render its child position and then
// moveInputFinished would immediately overwrite it with whatever the board's
// DOM happens to hold mid-animation.
let playedMove = false;

function commitPlacement() {
  const fen = withPlacement(current, board.getPosition());
  if (fen === current) return;        // nothing actually moved
  history.push(current);
  render(fen);
}

function enableBoardInput() {
  board.enableMoveInput((event) => {
    if (event.type === INPUT_EVENT_TYPE.moveInputCanceled) {
      if (event.reason === MOVE_CANCELED_REASON.movedOutOfBoard)
        board.setPiece(event.squareFrom, null).then(commitPlacement);
      return;
    }
    if (event.type === INPUT_EVENT_TYPE.moveInputFinished) {
      if (playedMove) { playedMove = false; return; }
      commitPlacement();
      return;
    }
    if (event.type !== INPUT_EVENT_TYPE.validateMoveInput) return true;

    const uci = `${event.squareFrom}${event.squareTo}`;
    const moves = lastMoves || [];

    const exact = moves.find((m) => m.uci === uci);
    if (exact) {
      playedMove = true;
      history.push(current);
      render(exact.fen);
      return true;
    }

    const candidates = moves.filter(
      (m) => m.uci.length === uci.length + 1 && m.uci.startsWith(uci)
    );
    // Not a legal move: accept the drag anyway and let moveInputFinished
    // commit it as a relocation. Returning false here would snap the piece
    // back, which is the old play-only behaviour.
    if (candidates.length === 0) return true;

    if (candidates.length === 1) {
      playedMove = true;
      history.push(current);
      render(candidates[0].fen);
      return true;
    }

    // Several underpromotion choices are legal: ask the user which piece.
    playedMove = true;
    const fromFen = current;
    const color = event.piece.charAt(0); // "wp" -> "w", matches COLOR.white/black
    board.showPromotionDialog(event.squareTo, color, (result) => {
      if (result.type !== PROMOTION_DIALOG_RESULT_TYPE.pieceSelected) {
        render(fromFen, { push: false }); // canceled: snap back to the prior position
        return;
      }
      const letter = result.piece.charAt(1); // "wq" -> "q"
      const chosen = candidates.find((m) => m.uci === `${uci}${letter}`);
      if (!chosen) { render(fromFen, { push: false }); return; }
      history.push(fromFen);
      render(chosen.fen);
    });
    return true;
  });
}
```

- [ ] **Step 4: Strip the arming out of the tray drag and the init path**

In `enablePaletteDrag`, delete the `if (armed !== piece) setArmed(piece);` line and the `btn.dataset.dragged = "1";` line, and make the drop commit immediately:

```js
      const square = squareFromTarget(document.elementFromPoint(e.clientX, e.clientY));
      if (!square) return;                      // dropped off the board: no-op
      board.setPiece(square, piece).then(commitPlacement);
```

In `buildPalette`, delete the `btn.addEventListener("click", …)` binding and the `#btn-erase` / `#btn-arrange` wiring, keeping only the sprite construction, `enablePaletteDrag(btn, piece)` and the `#btn-clear-board` handler. `#btn-clear-board` becomes:

```js
  document.getElementById("btn-clear-board").addEventListener("click", () => {
    board.setPosition(EMPTY_PLACEMENT, false).then(() => {
      const fen = composeFen(EMPTY_PLACEMENT, splitFen(current).stm);
      history.push(current);
      render(fen);
    });
  });
```

In `initExplorer`, replace `enableDragToPlay()` with `enableBoardInput()`, delete the `#btn-done-editing` listener, and delete the two `setArmed(null, { commit: false })` calls (the FEN form's and the `hashchange` handler's) along with the `if (armed !== null)` branch in the `stm-select` handler.

Remove the now-unused imports if `POINTER_EVENTS` is no longer referenced — check with:

```bash
grep -n "POINTER_EVENTS" src/packages/web/helpmate_web/static/js/explorer.js
```

- [ ] **Step 5: Remove the panel from the markup**

In `index.html`, replace the whole `<div id="palette" class="palette">…</div>` block with just the tray container and the Clear board control (Task 3 gives these their final placement):

```html
        <div id="palette-pieces" class="palette-pieces"></div>
        <button type="button" id="btn-clear-board">Clear board</button>
```

- [ ] **Step 6: Remove the armed-state CSS**

In `css/app.css`, delete the `.palette button[aria-pressed="true"]` rule and its comment, and the `.palette` panel rule. Keep `.palette-pieces` and `.drag-ghost`.

- [ ] **Step 7: Run the tests**

Run: `taskset -c 0-3 make lint && taskset -c 0-3 make jstest && taskset -c 0-3 make test-web && taskset -c 0-3 python -m pytest tests/repo -v`
Expected: all pass.

- [ ] **Step 8: Prove the relocation path is real**

The subtlest thing here is `playedMove`. Temporarily delete the `if (playedMove) { playedMove = false; return; }` guard, run `taskset -c 0-3 make test-web`, and confirm `test_a_legal_drag_plays_the_move` FAILS (the finish handler overwrites the played move). Restore and confirm it passes. Record both.

- [ ] **Step 9: Drive it by hand**

Playwright's synthetic pointer is cleaner than a real one. At `http://127.0.0.1:8660/` (restart with `helpmate-server --tables ~/tb --port 8660` if down; reinstall the web package first), confirm and report each:

1. Drag `Kh7`→`h8` — plays the move, side to move flips, verdict changes.
2. Drag `Qg1`→`d4` — relocates, side to move unchanged, verdict recomputes.
3. Drag `Qd4` off the left edge — the queen disappears, the summary names the missing piece or recomputes.
4. Drag a black rook from the tray onto `e5` — it lands and evaluates, with nothing clicked first.
5. Press **Back** three times — every one of the above is undone in order.
6. Confirm no Erase, Arrange or Done button exists anywhere.

- [ ] **Step 10: Commit**

```bash
git add src/packages/web/helpmate_web/static/js/explorer.js \
        src/packages/web/helpmate_web/static/index.html \
        src/packages/web/helpmate_web/static/css/app.css \
        src/packages/web/tests/ui/test_dashboard.py
git commit -m "feat(web): the board has no modes

A drag that matches a legal move plays it, any other drag relocates the
piece, and a drag off the board deletes it. Editing is never gated behind
a control, so the four-way arming, Erase, Arrange, Done -- evaluate, the
armed ring, the hint copy and the commitBoard/editBaseline machinery all
go. This removes more code than it adds.

syzygy configures its board movable.free with deleteOnDropOff permanently
and gates editing behind nothing; the conflict the arming existed to
solve only existed because click-to-place shared pointerdown with drag.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Trays flank the board, controls collapse to one line

**Files:**
- Modify: `src/packages/web/helpmate_web/static/index.html`
- Modify: `src/packages/web/helpmate_web/static/css/app.css`
- Modify: `src/packages/web/helpmate_web/static/js/explorer.js` (tray build + flip)
- Test: `src/packages/web/tests/ui/test_dashboard.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_the_trays_flank_the_board_black_above_white_below(page, server):
    page.goto(server)
    page.wait_for_selector("#move-list li")
    board = page.eval_on_selector("#board", "e => e.getBoundingClientRect()")
    black = page.eval_on_selector("#tray-black", "e => e.getBoundingClientRect()")
    white = page.eval_on_selector("#tray-white", "e => e.getBoundingClientRect()")
    assert black["bottom"] <= board["top"] + 1, "the black tray is not above the board"
    assert white["top"] >= board["bottom"] - 1, "the white tray is not below the board"


def test_the_trays_swap_when_the_board_is_flipped(page, server):
    # The placement is only meaningful because each tray sits on its own
    # colour's side; after a flip, black is at the bottom and so is its tray.
    page.goto(server)
    page.wait_for_selector("#move-list li")
    page.click("#btn-flip")
    page.wait_for_function(
        "() => document.getElementById('tray-black').getBoundingClientRect().top"
        " > document.getElementById('board').getBoundingClientRect().top")
    board = page.eval_on_selector("#board", "e => e.getBoundingClientRect()")
    black = page.eval_on_selector("#tray-black", "e => e.getBoundingClientRect()")
    white = page.eval_on_selector("#tray-white", "e => e.getBoundingClientRect()")
    assert black["top"] >= board["bottom"] - 1, "the black tray did not move below"
    assert white["bottom"] <= board["top"] + 1, "the white tray did not move above"


def test_the_fen_applies_on_enter_without_a_set_button(page, server):
    page.goto(server)
    page.wait_for_selector("#move-list li")
    assert page.eval_on_selector_all("#fen-form button[type=submit]", "e => e.length") == 0
    page.fill("#fen-input", "7k/8/5K2/8/8/8/8/6Q1 w - - 0 1")
    page.press("#fen-input", "Enter")
    page.wait_for_function(
        "() => document.getElementById('stm-select').value === 'w'")
```

- [ ] **Step 2: Run to verify they fail**

Run: `taskset -c 0-3 make test-web`
Expected: three failures — `#tray-black` does not exist, and the submit button does.

- [ ] **Step 3: Restructure the rail markup**

Replace the board column's contents in `index.html` with:

```html
    <div class="rail board-col">
      <div class="board-pin">
        <div id="tray-black" class="tray" data-color="b"></div>
        <div id="board"></div>
        <div id="tray-white" class="tray" data-color="w"></div>

        <form id="fen-form" class="board-controls">
          <label class="sr-label" for="fen-input">Position (FEN)</label>
          <input id="fen-input" type="text" spellcheck="false" autocomplete="off"
                 placeholder="8/7k/5K2/8/8/8/8/6Q1 b - - 0 1">
          <label class="inline" for="stm-select">To move
            <select id="stm-select">
              <option value="b">Black</option>
              <option value="w">White</option>
            </select>
          </label>
          <button type="button" id="btn-flip">Flip</button>
          <button type="button" id="btn-clear-board">Clear board</button>
          <button type="button" id="btn-back" disabled>Back</button>
        </form>
      </div>
    </div>
```

The `Set` button is gone — a `<form>` submits on Enter in a text input by itself, and `#fen-form`'s existing submit handler already does the work.

- [ ] **Step 4: Build the trays by colour**

In `explorer.js`, replace the single `PALETTE` list and `buildPalette`'s container lookup with two trays:

```js
const TRAY = {
  b: ["bk", "bq", "br", "bb", "bn", "bp"],
  w: ["wk", "wq", "wr", "wb", "wn", "wp"],
};
```

and in `buildPalette`, for each colour, append its six buttons to `#tray-${colour}`. Keep `enablePaletteDrag(btn, piece)` per button and the `#btn-clear-board` handler.

- [ ] **Step 5: Swap the trays on flip**

The trays are ordered by CSS, so flipping is a class on the pin. In `initExplorer`'s `#btn-flip` handler:

```js
  document.getElementById("btn-flip").addEventListener("click", () => {
    const black = board.getOrientation() === COLOR.white;   // after the flip below
    board.setOrientation(black ? COLOR.black : COLOR.white);
    // Each tray sits on the side of the board its own colour occupies; leaving
    // them put after a flip would make them two anonymous rows of buttons.
    document.querySelector(".board-pin").classList.toggle("flipped", black);
  });
```

- [ ] **Step 6: Style the trays and the control line**

Replace the `.palette*` rules in `css/app.css` with:

```css
/* The trays are the affordance -- no panel, no label, no hint copy. Each sits
   on the side of the board its own colour occupies, and swaps on a flip. */
.board-pin { display: flex; flex-direction: column; gap: var(--s2); }
.board-pin.flipped { flex-direction: column-reverse; }
.tray {
  display: grid; grid-template-columns: repeat(6, 1fr);
  gap: .3rem; width: 100%; max-width: 460px; margin-inline: auto;
}
.tray button {
  aspect-ratio: 1; padding: .15rem; display: grid; place-items: center;
  background: var(--sunk); border: 1px solid var(--rule); border-radius: 4px;
  cursor: grab; touch-action: none;
}
.tray button:active { cursor: grabbing; }
.tray button svg { width: 100%; height: 100%; display: block; }

/* One line: the position, whose turn it is, and the three things you can do
   to the board. */
.board-controls {
  display: flex; flex-wrap: wrap; align-items: center; gap: var(--s2);
  width: 100%; max-width: 460px; margin-inline: auto;
}
.board-controls #fen-input {
  flex: 1 1 100%; font-family: var(--mono); font-size: var(--f1);
}
```

`.board-pin.flipped` reverses the column, so the FEN line would move to the top — it must not. Keep it outside the reversal by giving it `order: 1` in the flipped case:

```css
.board-pin.flipped .board-controls { order: -1; }
```

- [ ] **Step 7: Run the tests**

Run: `taskset -c 0-3 make lint && taskset -c 0-3 make test-web && taskset -c 0-3 python -m pytest tests/repo -v`
Expected: all pass, including the pre-existing `test_below_the_breakpoint_the_columns_stack_and_nothing_is_hidden`, which asserts `#palette` is visible at 420px — **update that selector to `#tray-white`**, since `#palette` no longer exists.

- [ ] **Step 8: Look at it**

Screenshot the explorer at 1280px and 420px in both themes. Confirm: the trays read as belonging to the board rather than as a toolbar; the control line does not wrap awkwardly at 420px; and after pressing Flip the black tray is genuinely below. Report what you saw per image.

- [ ] **Step 9: Commit**

```bash
git add src/packages/web/helpmate_web/static/index.html \
        src/packages/web/helpmate_web/static/css/app.css \
        src/packages/web/helpmate_web/static/js/explorer.js \
        src/packages/web/tests/ui/test_dashboard.py
git commit -m "feat(web): trays flank the board, controls collapse to one line

Black above, white below -- each tray on the side of the board its colour
occupies, swapping when the board is flipped, because that placement is
the entire rationale. The trays are the affordance, so the Edit position
panel, its eyebrow and its hint copy are gone, and so is Set: a form with
one text input submits on Enter.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Chips for the banded groups

**Files:**
- Modify: `src/packages/web/helpmate_web/static/js/explorer.js` (`renderMoveList`)
- Modify: `src/packages/web/helpmate_web/static/js/lib/moves.js` (`moveBadge`)
- Modify: `src/packages/web/helpmate_web/static/css/app.css`
- Test: `src/packages/web/tests/js/moves.test.js`, `src/packages/web/tests/ui/test_dashboard.py`

**Interfaces:**
- Consumes: `groupMoves(...)[].bands` from Task 1.

- [ ] **Step 1: Write the failing tests**

Append to `tests/js/moves.test.js`:

```js
test("a badge is only produced where it says something a band label cannot", () => {
  // The optimal group's count differs per move: it keeps a badge.
  assert.equal(moveBadge(M("Kh8", 1, 1, { optimal: true })), "only reply");
  assert.equal(moveBadge(M("Kh6", 1, 3, { optimal: true })), "3 ways");
  // Slower and dead moves are banded, so their badge would repeat the band.
  assert.equal(moveBadge(M("Qa7", 2, 9)), null);
  assert.equal(moveBadge(M("Qg8", null, 0, { solvable: false })), null);
});
```

Append to `tests/ui/test_dashboard.py`:

```python
def test_slower_moves_render_as_chips_under_a_distance_band(page, server):
    page.goto(f"{server}/#fen={quote(THREE_GROUPS)}")
    page.wait_for_selector("#move-list li")
    labels = page.eval_on_selector_all(
        "#move-list section[data-group=slower] .band-label",
        "els => els.map(e => e.textContent.trim())")
    assert labels and all(l.startswith("h#") for l in labels), labels
    # the chips carry no badge -- the band label already said it
    assert page.eval_on_selector_all(
        "#move-list section[data-group=slower] .badge", "e => e.length") == 0
    # and the optimal group still does
    assert page.eval_on_selector_all(
        "#move-list section[data-group=optimal] .badge", "e => e.length") > 0


def test_every_legal_move_is_still_one_list_item(page, server):
    page.goto(f"{server}/#fen={quote(THREE_GROUPS)}")
    page.wait_for_selector("#move-list li")
    shown = page.eval_on_selector_all("#move-list li", "els => els.length")
    api = page.evaluate("""async () => {
      const fen = document.getElementById('fen-input').value;
      const r = await fetch('/v1/moves?fen=' + encodeURIComponent(fen));
      return (await r.json()).moves.length;
    }""")
    assert shown == api, f"{shown} rendered vs {api} legal moves"


def test_a_chip_plays_its_move(page, server):
    page.goto(f"{server}/#fen={quote(THREE_GROUPS)}")
    page.wait_for_selector("#move-list section[data-group=slower] li")
    before = page.input_value("#fen-input")
    page.click("#move-list section[data-group=slower] li")
    page.wait_for_function("b => document.getElementById('fen-input').value !== b", arg=before)
```

- [ ] **Step 2: Run to verify they fail**

Run: `taskset -c 0-3 make jstest && taskset -c 0-3 make test-web`
Expected: the badge test fails (it returns a string), and the UI tests fail on the missing `.band-label`.

- [ ] **Step 3: Reduce `moveBadge` to the case that earns it**

In `lib/moves.js`:

```js
// A badge earns its place only when it says something the group heading and
// the band label cannot. That is true in exactly one group: the optimal
// moves, whose child solution count differs per move and is the property a
// composer is reading the list for. Slower and dead moves are banded by
// distance, so a per-move badge would repeat the band label N times -- which
// is what made the list 25 rows of identical text.
export function moveBadge(move) {
  if (move.solvable !== true) return null;
  if (move.optimal !== true) return null;
  return waysLabel(move.count);
}
```

- [ ] **Step 4: Render bands and chips**

In `explorer.js`, replace `renderMoveList`'s per-group body so a group with `bands` renders bands of chips and a group without renders rows:

```js
function renderMoveRow(m) {
  const li = document.createElement("li");
  li.className = moveClass(m);
  li.dataset.san = m.san;
  const san = document.createElement("span");
  san.className = "san";
  san.textContent = m.san;
  li.appendChild(san);
  const text = moveBadge(m);
  if (text) {
    const badge = document.createElement("span");
    badge.className = "badge";
    badge.textContent = text;
    li.appendChild(badge);
  }
  // Every row is clickable, including the dead ones: walking into a position
  // with no helpmate is a legitimate thing to want to look at.
  li.addEventListener("click", () => { history.push(current); render(m.fen); });
  return li;
}

function renderGroup(sec, g) {
  if (!g.bands) {
    const ul = document.createElement("ul");
    for (const m of g.moves) ul.appendChild(renderMoveRow(m));
    sec.appendChild(ul);
    return;
  }
  for (const band of g.bands) {
    const wrap = document.createElement("div");
    wrap.className = "band";
    if (band.label) {
      const lab = document.createElement("span");
      lab.className = "band-label";
      lab.textContent = band.label;
      wrap.appendChild(lab);
    }
    const ul = document.createElement("ul");
    ul.className = "chips";
    for (const m of band.moves) ul.appendChild(renderMoveRow(m));
    wrap.appendChild(ul);
    sec.appendChild(wrap);
  }
}
```

and call `renderGroup(sec, g)` where the old `<ul>` construction was, keeping the existing `<h3 class="eyebrow">` heading exactly as it is.

- [ ] **Step 5: Style the chips**

**First, close a specificity collision.** The existing row rule is
`.move-group li { display: flex; padding: .4rem .55rem; … }` at specificity
(0,1,1) — identical to `.chips li`, so which one wins depends purely on source
order. That is exactly the kind of rule that half-applies and looks like a
layout bug. Scope the row rule to direct children before adding the chip
rules, so the two can never compete:

```css
/* Rows are the group's own <ul> children. Chips live in a band's <ul>, so
   this must not reach them -- at equal specificity the winner would be
   whichever rule came last in the file. */
.move-group > ul > li { /* ...the existing row declarations, unchanged... */ }
```

Apply the same narrowing to every `.move-group li…` selector that styles a
row (`li:hover`, `li .san`, `li .badge`, `li.optimal`, `li.slower`, `li.dead`
and `li.optimal.only`). Then add:

```css
/* A band is a shared fact stated once, then the moves it covers. */
.band { display: grid; grid-template-columns: 3.2rem 1fr; gap: var(--s2);
        align-items: start; margin-top: var(--s1); }
.band-label { font-family: var(--mono); font-size: var(--f1);
              color: var(--ink-soft); text-align: right; padding-top: .25rem; }
.chips { list-style: none; margin: 0; padding: 0;
         display: flex; flex-wrap: wrap; gap: .25rem; }
.chips li {
  font-family: var(--mono); font-size: var(--f1); font-weight: 600;
  padding: .2rem .45rem; border-radius: 3px; border: 1px solid var(--rule);
  cursor: pointer;
}
.chips li:hover { border-color: var(--accent); }
.chips li .san { min-width: 0; }
.chips li.dead .san { color: var(--ink-faint); text-decoration: line-through; }
```

The `.band` grid has no label cell content for the dead group; that is intentional — the empty first column keeps the chips aligned with the bands above.

- [ ] **Step 6: Run the tests**

Run: `taskset -c 0-3 make lint && taskset -c 0-3 make jstest && taskset -c 0-3 make test-web && taskset -c 0-3 python -m pytest tests/repo -v`
Expected: all pass.

- [ ] **Step 7: Measure the reduction**

The point of this task is height. On `THREE_GROUPS`, record `document.getElementById('move-list').getBoundingClientRect().height` before and after (use `git stash` to measure the old value if you did not record it at Step 2). Report both numbers.

- [ ] **Step 8: Commit**

```bash
git add src/packages/web/helpmate_web/static/js/explorer.js \
        src/packages/web/helpmate_web/static/js/lib/moves.js \
        src/packages/web/helpmate_web/static/css/app.css \
        src/packages/web/tests/js/moves.test.js \
        src/packages/web/tests/ui/test_dashboard.py
git commit -m "feat(web): chips under a distance band for the non-optimal groups

Measured on 7k/8/5K2/8/8/8/8/6Q1 w, the Slower group was 25 rows whose
badges carried two distinct facts. The distance becomes the band label,
the badge disappears, and the moves become chips. The optimal group keeps
rows: its per-move solution count is what the list exists to show.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: The table band is one line, and weight marks what you can act on

**Files:**
- Modify: `src/packages/web/helpmate_web/static/js/stats-view.js`
- Modify: `src/packages/web/helpmate_web/static/js/explorer.js`
- Modify: `src/packages/web/helpmate_web/static/css/app.css`
- Test: `src/packages/web/tests/ui/test_dashboard.py`

**Interfaces:**
- Produces: `renderTableLine(box, stats)` in `js/stats-view.js`.

- [ ] **Step 1: Write the failing tests**

```python
def test_the_explorer_table_band_is_one_line_with_no_histogram(page, server):
    page.goto(server)
    page.wait_for_selector("#table-stats-body")
    assert "KQvk" in page.inner_text("#table-stats")
    # the histograms live on Materials, one click away
    assert page.eval_on_selector_all("#table-stats .hist", "e => e.length") == 0
    assert page.eval_on_selector_all("#table-stats .tiles", "e => e.length") == 0
    h = page.eval_on_selector("#table-stats", "e => e.getBoundingClientRect().height")
    assert h < 120, f"the band is {h:.0f}px tall"


def test_actionable_controls_are_weighted(page, server):
    page.goto(server)
    page.wait_for_selector("#move-list li")
    for sel in ("#btn-flip", "#btn-clear-board", "#btn-back", "#btn-export-pgn"):
        w = page.eval_on_selector(sel, "e => getComputedStyle(e).fontWeight")
        assert int(w) >= 600, f"{sel} is weight {w}"
    # inert text is not
    w = page.eval_on_selector("#position-summary", "e => getComputedStyle(e).fontWeight")
    assert int(w) < 600, f"the verdict is weight {w}"
```

- [ ] **Step 2: Run to verify they fail**

Run: `taskset -c 0-3 make test-web`
Expected: both fail — the band renders tiles and histograms, and the buttons are weight 400.

- [ ] **Step 3: Add the one-line renderer**

Append to `js/stats-view.js`:

```js
// The explorer's band: which table answered, how deep it goes, how much of it
// is solvable. Everything else about the material is one click away on
// Materials, and repeating it under every position was ~900px per screen.
export function renderTableLine(box, s) {
  box.textContent = "";
  const cells = cellSummary(s);
  const line = el("p", "table-line");
  const name = el("b", null, s.material);
  line.append(name, ` · ${mateLengthLabel(s)} · ${fmtCount(cells.solvable)} solvable`);
  box.appendChild(line);
}
```

- [ ] **Step 4: Use it in the explorer**

In `explorer.js`, change the import to bring in `renderTableLine` instead of `renderStats`, and replace the render call in `showTableStats`:

```js
  renderTableLine(body, statsCache.get(material));
```

- [ ] **Step 5: Apply the weight rule**

In `css/app.css`, add after the shared `button, select, input` rule:

```css
/* Weight marks what you can act on. That is the affordance cue, which is why
   the two board controls below can drop their borders without becoming
   ambiguous -- and why nothing inert is ever 600. */
nav button, .board-controls button, #btn-export-pgn, #btn-open-material,
.move-group li, .chips li { font-weight: 600; }

#btn-flip, #btn-clear-board { border-color: transparent; background: none; }
#btn-flip:hover:not(:disabled), #btn-clear-board:hover:not(:disabled) {
  border-color: var(--accent);
}

.table-line { margin: 0; font-size: var(--f2); }
.table-band { padding: var(--s2) var(--s3); }
```

- [ ] **Step 6: Run the tests**

Run: `taskset -c 0-3 make lint && taskset -c 0-3 make test-web && taskset -c 0-3 python -m pytest tests/repo -v`
Expected: all pass. The accent-confinement guard must still pass — every new `var(--accent` above is inside a `:hover`.

- [ ] **Step 7: Check nothing else used `renderStats` from the explorer**

```bash
grep -n "renderStats\|renderTableLine\|renderAggregate" \
  src/packages/web/helpmate_web/static/js/*.js
```
Materials must still call `renderStats` with the default prefix and `renderAggregate` for the corpus view. If `idPrefix` now has no caller, say so in the report rather than deleting it — Task 6 decides.

- [ ] **Step 8: Commit**

```bash
git add src/packages/web/helpmate_web/static/js/stats-view.js \
        src/packages/web/helpmate_web/static/js/explorer.js \
        src/packages/web/helpmate_web/static/css/app.css \
        src/packages/web/tests/ui/test_dashboard.py
git commit -m "feat(web): one-line table band, and weight as the affordance cue

The explorer repeated the whole Materials view under every position at
about 900px a screen; it now states the table, its depth and its solvable
count on one line with a link. Actionable controls go to 600 and nothing
inert does, which lets Flip and Clear board drop their borders.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Docs, 0.12.0, and the whole gate

**Files:**
- Modify: `README.md`, `docs/USAGE.md`, `CHANGELOG.md`, `VERSION`, `pyproject.toml`, `src/packages/{api,web}/pyproject.toml`, `src/packages/api/helpmate_server/__init__.py`, `src/packages/web/helpmate_web/__init__.py`

- [ ] **Step 1: Bump every version site**

```bash
grep -rn "0\.11\.0" --include="*.toml" --include="*.py" --include="VERSION" \
  --include="*.md" . | grep -v "^./build/" | grep -v CHANGELOG | grep -v "docs/superpowers/"
```

All become `0.12.0`. **The trap:** `src/packages/api/pyproject.toml` pins `helpmate>=0.11.0,<0.12` — bump it to `helpmate>=0.12.0,<0.13` in the same edit, or the API package excludes its own sibling. `README.md`'s theme-table line claims its output is "copied verbatim from its real output on this checkout (`helpmate 0.11.0`)" — this branch touches no C++, so re-run `helpmate themes`, confirm the table is unchanged, then update the number. If you cannot build, say so rather than bumping it silently.

- [ ] **Step 2: Write the CHANGELOG entry**

```markdown
## [0.12.0] - 2026-08-12

Dashboard UX round 2: no modes, and say the shared fact once.

### Changed
- **The board has no editing modes.** A drag that matches a legal move plays
  it, any other drag relocates the piece, and a drag off the board deletes it.
  **Erase**, **Arrange** and **Done — evaluate** are gone, along with
  click-to-place and the armed-state ring. Back undoes a relocation as well as
  a move.
- **The piece trays flank the board** — black above, white below, each on the
  side of the board its colour occupies, swapping when the board is flipped.
- **Slower and no-mate moves render as chips under a distance band.** Within
  one distance every badge read the same string; the distance is now stated
  once. The optimal group keeps its rows, because its per-move solution count
  is what the list exists to show.
- **The explorer's table band is one line** with a link to Materials, where
  the histograms already live.
- **Weight marks what you can act on**: actionable controls are 600, inert
  text is not, and **Flip** and **Clear board** drop their borders.
- The FEN field applies on Enter; the **Set** button is gone. With no
  click-to-place, the FEN field is the keyboard route to an arbitrary
  position.
```

- [ ] **Step 3: Update the docs**

In `docs/USAGE.md` and `README.md`, replace every description of the old editor — arming a piece, Erase, Arrange, Done — with the one-rule model, and say plainly that a relocation onto a square that happens to be a legal move will play that move, and that Back undoes it. Document the tray placement and the flip swap. Note the keyboard limitation honestly.

- [ ] **Step 4: Run the whole gate and read every output**

```bash
taskset -c 0-3 make lint
taskset -c 0-3 make typecheck
taskset -c 0-3 make jstest
taskset -c 0-3 python -m pytest tests/repo -v
taskset -c 0-3 python -m pytest src/packages/api/tests -v
taskset -c 0-3 make test-web
taskset -c 0-3 make format-check
```

- [ ] **Step 5: Re-measure the clutter**

The brief was "the UI looks cluttered". Measure it, at 1280px on the landing position:

```bash
taskset -c 0-3 python3 - <<'PY'
from playwright.sync_api import sync_playwright
with sync_playwright() as pw:
    b = pw.chromium.launch(args=["--no-sandbox"])
    pg = b.new_page(viewport={"width": 1280, "height": 1000})
    pg.goto("http://127.0.0.1:8660/")
    pg.wait_for_selector("#move-list li")
    n = pg.evaluate("""() => {
      const vis = s => [...document.querySelectorAll(s)].filter(e => e.offsetParent !== null);
      return { buttons: vis('#panel-explorer button').length,
               eyebrows: vis('#panel-explorer .eyebrow').length,
               paragraphs: vis('#panel-explorer p').length,
               height: document.documentElement.scrollHeight };
    }""")
    print(n)
    b.close()
PY
```

Baseline before this plan: **20 buttons, 10 eyebrows, 5 paragraphs, 2915px.** Report the new figures beside them. If the page is not materially shorter, say so plainly — that is the result, not a reason to adjust the measurement.

- [ ] **Step 6: Screenshots**

Explorer, Materials and Search × light and dark at 1280px, plus explorer at 420px. Confirm no control became invisible when its border came off, that the trays read as part of the board, and that nothing scrolls sideways. Report per image.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "release: bump 0.11.0 -> 0.12.0 for dashboard UX round 2

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage**

| Spec section | Task |
|---|---|
| One rule, no modes; occupied-square replacement; promotion survives | 2 |
| Back undoes relocations; every drop pushes history | 2 |
| Removed: click-to-place, Erase, Arrange, Done, armed ring, commitBoard | 2 |
| Kept: Clear board, kingProblem short circuit | 2 |
| Trays flank the board, swap on flip | 3 |
| Controls collapse to one line; FEN applies on Enter; keyboard path | 3 |
| Rows where the datum differs, chips where it does not | 1, 4 |
| `#move-list li` still selects exactly the moves | 4 (test) |
| Table band is one line | 5 |
| Weight marks what you can act on; borders come off | 5 |
| No new colours; accent confinement | Global Constraints, 5 |
| Re-measure the clutter | 6 |

**Type consistency** — `groupMoves` returns `{ key, label, moves, bands }` in Task 1 and is destructured that way in Task 4. `moveBadge` returns `string | null` from Task 4 onward and its only caller checks for null. `renderTableLine(box, stats)` is defined in Task 5 Step 3 and called in Step 4.

**Ordering** — 1 before 4. 2 before 3 (3 moves markup that 2 strips). 5 depends on nothing but touches CSS 3 also edits, so run it after 3. 6 last.

**Known risk carried deliberately** — `playedMove` is module state shared between two events of the same gesture. Task 2 Step 8 mandates proving the guard is load-bearing; if a future gesture can interleave two drags, that flag is where it will break.
