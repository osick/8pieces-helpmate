# Dashboard UX — rail and readout

Status: proposed
Supersedes nothing; extends `2026-08-09-dashboard-redesign-design.md`, which
established the palette and the move-list ordinal. Both survive unchanged.

## Why

The 0.10.0 redesign fixed how the *move list* reads. It did not touch how the
*pages* are built, and three problems became visible once the dashboard was
run against the full 295-table corpus:

1. **The board overflows its own column.** Between 860px and ~1150px viewport
   the grid column is `min(460px, 40%)` while `#board` is `min(88vw, 460px)`
   — two different sizing rules for the same box. Measured at 960px: a 460px
   board in a 368px column, its right edge 66px past the move list's left
   edge. It lands on top of the first move's SAN, the FEN field and the help
   copy.
2. **67 of 295 tables report a mate length that does not exist.** A material
   where nothing is solvable stores `max_dtm = 255` (the `DTM_UNSOLVABLE`
   sentinel) and an empty histogram. `materials.js` divides it by two, so
   `KBvk` — king and bishop cannot mate — currently reads **"longest mate
   h#127.5"**.
3. **The Materials page is 12,005px tall.** All 295 tables render as one
   unscrolled list; the statistics panel is a postage stamp at the top of it.

Alongside those, the brief asks for a centred board with drag-and-drop
editing, a grey/white split carried across every page, per-material
statistics on the explorer, an abort control on search, and a corpus-wide
statistics view.

## The structural idea: every page is a rail and a readout

The grey/white split in the brief is worth more than a colour change, because
it can carry a rule:

> **Grey is what you manipulate. White is what the tables say.**

Applied to all three panels it gives the dashboard one skeleton instead of
three ad-hoc layouts:

```
EXPLORER                          MATERIALS                      SEARCH
┌──────────┬───────────────┐      ┌──────────┬────────────┐      ┌──────────┬────────────┐
│  RAIL    │   READOUT     │      │  RAIL    │  READOUT   │      │  RAIL    │  READOUT   │
│ ┌──────┐ │ dtm 1 (h#0.5) │      │ [filter] │ All tables │      │ material │ searching… │
│ │board │ │               │      │ ─────────│ 295 · 4 GB │      │ dtm      │  6s of 30s │
│ │centrd│ │ OPTIMAL 2     │      │ ▸All     │ [tiles]    │      │ count    │    [Stop]  │
│ └──────┘ │ ▌Kh8  only    │      │ 3 PIECES │ ▁▂▅█▆▃▂▁   │      │ starts   │ ────────── │
│ flip back│ ▌Kh6  3 ways  │      │  KQvk    │ DEEPEST    │      │ ends     │ 1 8/7k/…   │
│ FEN […]  │               │      │ 4 PIECES │ KBvkqp h#17│      │ themes   │ 2 …        │
│ ♔♕♖♗♘♙   │ SLOWER 4      │      │  KQQvk   │ 67 tables  │      │ max      │            │
│ ♚♛♜♝♞♟   │ …             │      │  (scrolls│  no mate   │      │ [Search] │ [↓ FENs]   │
├──────────┴───────────────┤      └──────────┴────────────┘      └──────────┴────────────┘
│ THIS TABLE · KQvk        │
│ [tiles] ▁▂▅█▆▃▂ histogram│
└──────────────────────────┘
```

Rail and readout are **surfaces**, not containers full of cards. Today the
explorer is a grey field with white boxes floating on it; the palette, the FEN
form and the tiles each draw their own border. Once the two columns are
themselves surfaces, those borders are redundant and come off. The page gets
quieter while gaining structure — the boldness is spent on the split, not on
the boxes.

### Tokens

No new hex values. The two surfaces are **semantic aliases** over the existing
palette, so dark mode needs no extra work and the `2026-08-09` colour
reasoning stands untouched:

```css
--rail:    var(--ground);    /* #edebe9 light · #161512 dark */
--readout: var(--panel);     /* #ffffff light · #262421 dark */
```

In light mode the rail is darker than the readout; in dark mode it is darker
still relative to the readout, because `--panel` (#262421) sits above
`--ground` (#161512). The relationship — rail recedes, readout advances —
holds in both themes rather than inverting.

One consequence to handle rather than discover: `.tile` currently fills with
`--panel` and draws a border, which on a `--panel` readout leaves it invisible
except for its rule. On the readout, tiles and charts fill with `--sunk` and
drop the border. Inputs and buttons keep `--panel` — white-on-grey inside the
rail is what makes them read as controls.

`tests/repo/test_accent_confined_to_focus_and_hover.py` stays in force: the
accent appears only in `:focus-visible` and `:hover` selectors. Nothing in
this design introduces a coloured surface.

## Board

**Sizing.** One rule, not two. The board fills its column up to its maximum
and centres in it:

```css
#board { width: 100%; max-width: 460px; margin-inline: auto; aspect-ratio: 1; }
```

and the grid becomes `minmax(300px, 460px) minmax(320px, 1fr)`, so the column
can never be narrower than the board is willing to be. The overflow is then
impossible by construction rather than by choosing matching magic numbers.

**Framework.** `cm-chessboard` 8.7.5 stays. It is already vendored (MIT, plain
ES modules, no build step, nothing fetched at runtime — see
`static/vendor/README.md`), already drives drag-to-play and the promotion
dialog, and already ships the events the editor needs. chessground was
considered and rejected: it is the better board, and it is TypeScript plus
snabbdom, which would put a bundler into a repo that deliberately serves raw
modules out of site-packages.

**Editing gains drag, and keeps click.** Three new gestures:

| gesture | mechanism |
|---|---|
| palette → square | pointer capture on the palette button, ghost element follows the pointer, `squareFromPoint` on `pointerup`, then `board.setPiece` |
| square → square | `enableMoveInput` with a validate callback that always accepts, active only in edit mode |
| square → off-board | `INPUT_EVENT_TYPE.moveInputCanceled` with `MOVE_CANCELED_REASON.movedOutOfBoard`, then `board.setPiece(from, null)` |

Only the first needs new code; cm-chessboard raises the other two natively and
we currently ignore them.

Click-to-arm is **not** replaced. Drag is unreachable by keyboard and awkward
on touch, so it is the addition; arming a piece and clicking squares stays the
accessible path, and every existing UI test that drives the editor by clicking
keeps passing unchanged.

**The edit session becomes explicit.** Today leaving edit mode means clicking
the armed palette entry a second time, which takes three sentences of hint
copy to explain — a smell. Dragging a piece in from the palette has no armed
entry to click again, so the mode needs a real exit anyway. Edit mode gets one
primary action, **Done — evaluate**, and the hint shrinks to a line. Entering
edit mode is either arming a palette entry or dragging a piece onto the board.

**New pure module** `js/lib/board-edit.js`, node-testable with no DOM:

```js
export function squareFromPoint({ x, y }, rect, orientation)  // -> "e4" | null
```

The DOM wiring (pointer capture, ghost element) stays in `explorer.js`, where
the board instance lives.

## Explorer: the table's statistics, below

A full-width band under both columns, headed `THIS TABLE · KQvk`, carrying the
same tiles and two histograms the Materials panel draws, plus a link that
opens that material in Materials. Sample positions are omitted — the explorer
already is a position.

**Which material.** The client must not derive it from the FEN, because
`/v1/moves` answers colour-flipped positions from the mirrored table and the
statistics shown have to be the table that actually answered. `/v1/probe` and
`/v1/moves` therefore gain one field, `material`, naming the table they used.
One field removes all client-side guessing.

**When it fetches.** Keyed by material in a `Map`, so walking a game re-uses
the entry and only a capture or promotion costs a request.

**Sharing the renderer.** `renderStats` moves out of `materials.js` into
`js/stats-view.js` — a sibling, not `js/lib/`, because it builds DOM and
`lib/` is the node-unit-tested pure layer. Both panels call it. It takes an
option for whether to draw the sample-position list.

## Materials

**The rail scrolls, filters and groups.**

```
┌────────────────┐
│ filter: [kq  ] │   substring, case-insensitive, on the material name
│ ────────────── │
│ ▸ All tables   │   pinned, selected on load
│ 3 PIECES    3  │
│   KQvk  1.9 MB │
│ 4 PIECES   28  │
│   KQQvk        │
│   …            │   the rail scrolls; the page does not
└────────────────┘
```

The rail is `position: sticky` with its own `overflow-y: auto`, so the page
height stops being a function of the corpus size.

**"All tables" is the landing state**, replacing "Select a table to see its
statistics." It answers the brief's "overall statistics (any piece
combination)":

- tables, and their breakdown by piece count — measured on this corpus:
  1 three-piece, 10 four, 55 five, 220 six, **9 seven**
- total size on disk — 41.4 GB
- summed cells: solvable / no mate / illegal / total
- the mate-length histogram summed over every table (**71,007,150,643**
  positions that have a mate, across 35 distance buckets)
- solutions-per-position, summed
- **deepest tables**, ranked — `KBvkqp` h#17, `KBvkrp` h#16.5, `KRBvkp` h#16 —
  a cross-table fact that is invisible anywhere today
- **the 67 tables in which no helpmate exists at all**, named as such
- the generator-version spread, because the corpus is genuinely mixed —
  **seven versions, 0.1.0 through 0.9.1**, with 0.8.0 covering 159 of the 295
  — and a summary that hides that is lying by omission

**The sentinel is guarded, not divided.** `lib/stats.js` gains a named
`DTM_UNSOLVABLE = 255`. A table whose `max_dtm` is the sentinel (equivalently,
whose histogram is empty) renders as *"no helpmate exists in this material"*
— never as a distance. The aggregate excludes those tables from `max_dtm` and
from the deepest ranking, and counts them separately. The sidecar format is
not changed; this is a reader-side fix.

### `GET /v1/stats`

New endpoint, aggregate over every table in the catalog. Shape, with this
corpus's real values where they are known and `…` where they are per-corpus:

```json
{
  "tables": 295,
  "tables_by_pieces": {"3": 1, "4": 10, "5": 55, "6": 220, "7": 9},
  "tables_without_stats": 0,
  "size_bytes": 41378247168,
  "cells": {"solvable": "…", "unsolvable": "…", "invalid": "…", "total": "…"},
  "dtm_histogram": {"btm": {"0": "…"}, "wtm": {"1": "…"}},
  "uniqueness": {"btm": {}, "wtm": {}},
  "max_dtm": 34,
  "deepest": [{"material": "KBvkqp", "max_dtm": 34}],
  "no_helpmate": ["KBvk", "KNvk"],
  "generators": {"0.1.0": 11, "0.5.0": 5, "0.6.1": 57, "0.6.2": 25,
                 "0.8.0": 159, "0.8.2": 35, "0.9.1": 3}
}
```

`max_dtm` is a distance in plies, so the client renders it as `h#17`, not as
`34`. `deepest` carries plies for the same reason the sidecar does; the
formatting is the reader's job.

It reads the `.stats.json` sidecars, which is cheap — **295 sidecars, 13 MB,
0.17s measured cold** — and caches the result keyed on the catalog's
`(material, size_bytes)` set, so a newly generated or downloaded table
invalidates it and nothing else does. Remote-only tables have no local
sidecar; they are counted in `tables` and excluded from the sums, and the
response says how many were excluded rather than silently under-reporting.

## Search

**The timeout is currently reported as a wrong answer.** The server times out
at `--mine-timeout` (30s default) and replies `{fens: [], truncated: true,
note: "timeout"}`. `mine.js` ignores `note` and renders that as
`0 position(s) (truncated — raise max results for more)` — advice that cannot
help, on a result that was never computed. Fixed first:

> **Timed out after 30s.** No results yet — narrow the material, or drop the
> count/starts/ends filters.

**A Stop button and a visible budget.** The submit button flips to `Stop`
while a search is in flight, and the status line counts up against the
server's budget:

```
searching…  6s of 30s                                   [Stop]
```

`Stop` aborts via `AbortController`. It is honest about what that means:

> **Stopped.** The server finishes or drops this scan within 30s.

— because the scan runs in a `ThreadPoolExecutor(max_workers=2)` and
abandoning the response does not free the worker. Real cancellation is a
core-library change and belongs to the concurrency phase, not here.

The budget is not hardcoded: `/v1/health` gains `mine_timeout`, so the
displayed number is the server's actual setting.

**The form becomes the rail**, a vertical stack of labelled fields, which
gives the results the full width of the readout and puts Stop next to the
controls it stops.

## Non-goals

- No build step, no npm, no bundler, no chessground.
- No server-side cancellation of a running `mine` — concurrency phase.
- No change to the `.hm` format or the `.stats.json` sidecar schema. The
  sentinel is handled by readers.
- No puzzle page.
- No new colours. The `2026-08-09` palette is used as-is.

## Verification

Every gate the branch already has, plus:

**Node (`make jstest`)** — `squareFromPoint` across both orientations, board
edges and points outside the board; the sentinel guard in `lib/stats.js`; the
timeout and elapsed status strings; the aggregate's piece-count bucketing.

**API (pytest)** — `/v1/stats` shape; that a no-helpmate table is excluded
from `deepest` and `max_dtm` and listed in `no_helpmate`; that the cache
invalidates when the catalog changes and not otherwise; that `material`
appears on `/v1/probe` and `/v1/moves` and names the mirrored table on a
colour-flipped probe; that `/v1/health` reports `mine_timeout`.

**UI (Playwright)** — all 28 existing tests still pass. New:

- at 960px, 1024px and 1280px the board's right edge is left of the readout's
  left edge (the measured regression, pinned on both sides of the breakpoint)
- the board is centred in the rail within 1px
- dragging a piece from the palette onto a square places it
- dragging a piece off the board removes it
- the explorer's statistics band names the same material the API reported,
  and does not refetch when the next move keeps the material
- the Materials rail filters, and the page height stops scaling with the
  corpus
- `KBvk` says no helpmate exists and the string `h#127.5` appears nowhere
- Stop returns the form to its idle state and leaves the previous results
  untouched

Screenshots at 960px and 1280px in both themes, reviewed by eye — the 0.10.0
cycle's single best find was an invisible control under a fully green suite.
