# Puzzles, theme documentation, and a lighter shell

Status: proposed
Follows `2026-08-12-dashboard-ux-round-2-design.md` (v0.12.0). The rail/readout
skeleton, the no-modes board and the chip move list all stand.

**A word this project overloads.** "Theme" means two unrelated things here:
the **chess motifs** the tablebase detects (`set-play`, `mirror`, `excelsior`)
and the **colour theme** of the dashboard. This pass *documents the first* and
*deletes the second*. Everywhere below, an unqualified "theme" means a chess
motif; the colour one is always called the colour theme.

## Why

Six small things and two real features.

The small ones are all cases where the interface draws attention to itself
instead of to the position: a drag ghost that carries an opaque white card
around the screen, a page that visibly jumps when you play a move, a colour
theme switch nobody needs, a title that does not read as the product's name,
and no footer at all.

The two features are the ones the corpus has been earning the right to have.
295 tables holding 71 billion solvable positions can supply an endless stream
of **puzzles**, and the twelve motifs the generator detects deserve an
explanation somewhere better than a `title` attribute on a `<select>`.

## The measured jump

Clicking a move empties the move list before the fetch that will refill it:

```
 t(ms)  move-list
     2          0     <- render() clears it synchronously
    24        286     <- the response lands and it refills
```

For ~22ms everything below the list — the optimal lines, the PGN button, the
table band — leaps up 286px and drops back. On a slower link it is longer.

The rule this pass adopts: **replace, never clear-then-fill.** Build the new
content and swap it in atomically when the data arrives. This also removes an
existing inconsistency — `render()` clears the move list, lines and themes but
*not* the summary, which is why two tests were able to pass while reading a
previous position's verdict.

## The colour theme switch goes, and so does dark mode

One palette. Deleted: `js/theme-toggle.js`, `js/lib/theme-mode.js`, the
pre-paint `<head>` script, `tests/repo/test_theme_key_not_duplicated_silently.py`,
the `#theme-toggle` control, the `@media (prefers-color-scheme: dark)` block
and the `:root[data-theme="dark"]` block.

Every contrast ratio in this file was measured for both themes over two
cycles; only the light numbers survive, and the comments recording the dark
ones go with the blocks. The three-state comment at the top of `app.css`
stops being true and must be rewritten rather than left to mislead.

## The shell

**Title.** `helpmate tablebases` currently reads at `--f4` (1.15rem), barely
above body text, with the tagline competing beside it. It becomes the clear
first thing on the page. The tagline stays but recedes.

**Footer.** There is none. A plain one, with placeholder links the project can
fill in: the source repository, the dataset, the licence, and a line naming
what the corpus currently holds. Placeholders are marked as such in the markup
so nobody ships a dead link by accident.

**Drag ghost.** It clones the tray button, so it carries that button's `--sunk`
fill and border — an opaque card following the pointer. It becomes the piece
alone: transparent ground, no border, and smaller than the tray button so it
reads as *in flight* rather than as a control that has come loose.

## Puzzles

A new screen. The corpus supplies the problems; the tablebase grades them.

**Only positions with exactly one solution.** `count == 1` means there is a
single optimal line, so every move has one right answer and grading is a table
lookup rather than a judgement. Positions with duals come later, if at all.

**The solver plays the whole line, both sides.** A helpmate is cooperative:
Black moves first and helps White mate. The solver demonstrates the entire
solution, alternating colours, not just the first move.

**Grading.** After each move: a **check** if it matches the unique line, a
**cross** if not — and on a wrong move the correct one is shown. Past a
configurable error budget (**default 1**), the rest of the solution is
revealed. The run of check and cross marks along the line is the score.

**A session is ten puzzles**, drawn at random from the shipped set and
presented **in increasing difficulty**. Difficulty is ordered by two stored
facts: **mate length first** (a longer helpmate is harder), **piece count
second** (more material is harder at equal length).

**The set is a static file, and deliberately dumb.** A build-time script mines
one-solution positions across materials and depths and writes
`static/puzzles.json`: a flat array of `{fen, dtm}`. Piece count is derived
from the FEN, so nothing else is stored. A thousand entries is roughly 70 KB.
Regenerating it is re-running the script; nothing about the app changes.

**No new endpoint.** Opening a puzzle costs one `/v1/line` call for the
solution and the `/v1/moves` calls the board already makes. Grading compares
the played move against the expected one at that ply.

**The screen looks like the explorer**, because it is the same job with a
different question: the same rail with the board, the same readout beside it.
What differs is the readout's content — a prompt, the solved line so far with
its check and cross marks, and the two controls (**Show solution**,
**Next puzzle**).

```
┌──────────────────────┬────────────────────────────────┐
│  ♚♛♜♝♞♟              │ Puzzle 3 of 10 · KQvk · h#2    │
│  ┌────────────────┐  │ Black to move and help mate    │
│  │     board      │  │                                │
│  │                │  │  1. ✓ Kh8   ✓ Qg7#             │
│  └────────────────┘  │                                │
│  ♔♕♖♗♘♙              │  [ Show solution ] [ Next ]    │
└──────────────────────┴────────────────────────────────┘
```

## Theme documentation

A screen listing every motif the build detects, rendered from `/v1/themes` so
it can never drift from the binary: the name, what it means, and which input it
reads (`position`, `plane` or `solutions` — the `needs` field, which is what
decides whether a theme can answer on a saturated position).

Prose, not a table dump: the motifs group naturally into mate-picture
qualities (`pure`, `model`, `ideal`, `mirror`), move-sequence patterns
(`switchback`, `closed-walk`, `excelsior`), and structural facts (`set-play`,
`single-piece`). The screen says what the group means before listing its
members.

## Non-goals

- No build step, no bundler. `puzzles.json` is generated by a script that is
  run by hand and its output committed.
- No puzzle progress, scoring history or accounts. A session is ten puzzles
  and ends.
- No duals. One-solution positions only.
- No new API endpoints.
- No new colours — and with dark mode gone, fewer.

## Verification

**Node** — the puzzle session builder: ten puzzles, ordered by `(dtm, pieces)`,
drawn without repetition, from a set larger than ten. The grading function:
correct move, wrong move, error budget exhausted.

**API** — unchanged; the existing suites must stay green.

**UI** — a puzzle can be solved end to end and reports success; a wrong move
shows a cross and the correct move; exceeding the budget reveals the rest; the
colour-theme control is gone and no `data-theme` attribute is ever set; the
move list no longer collapses to zero height during a move (sample it during
the transition, as the diagnosis above did); the footer renders; the drag ghost
has no background.

**By eye** — the explorer and the puzzle screen at 1280px and 420px. The two
must look like the same product.
