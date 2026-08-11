# Dashboard redesign — Design

Date: 2026-08-09
Status: **approved by the user** (brainstorming session of 2026-08-09).
Origin: "I want the professionalization of the web UI because I want to
publish it soon", with syzygy-tables.info named as the UX benchmark.

Scope: the existing three-panel dashboard. **Out of scope and each getting its
own cycle:** the puzzle page (new feature), and concurrency under load.

## Why

The dashboard works and is honest, but it does not read as a published tool.
Three concrete defects, all measured against the current tree:

1. **The move list is not sorted at all.** Rows render in the order the C++
   move generator emits them — by piece and square — so optimal, slower and
   dead moves are interleaved arbitrarily (`explorer.js:147-159`).
2. **It discards most of what the server sends.** `/v1/moves` returns `dtm`,
   `count`, `optimal` and `solvable` per move; the row shows only SAN and the
   h#n notation.
3. **Dark mode is dead code and there is no responsive design.** `app.css`
   defines a complete dark palette under both `prefers-color-scheme` and
   `[data-theme]`, but nothing in the codebase ever sets `data-theme`; and
   there is not one `@media` width query in 242 lines.

## The benchmark, and what actually transfers

syzygy-tables.info was studied against its source. The headline finding is that
its move list is **not** sorted fastest-first, which is what we assumed:

```python
# server.py:521-530 — chained stable sorts, least significant first
grouped_moves[-2].sort(key=lambda m: m["uci"])
grouped_moves[-2].sort(key=lambda m: (m["dtm"] is None, m["dtm"]))
grouped_moves[-2].sort(key=lambda m: (m["dtz"] is None, m["dtz"]), reverse=True)
grouped_moves[-2].sort(key=lambda m: m["zeroing"], reverse=True)
grouped_moves[-2].sort(key=lambda m: m["capture"], reverse=True)
grouped_moves[-2].sort(key=lambda m: m["checkmate"], reverse=True)
```

Effective precedence: **checkmate → capture → zeroing → smallest |DTZ| →
smallest DTM → alphabetical**. DTM is merely a tiebreaker. The site's prose
says why: *"forcing captures or pawn moves while keeping a win in hand ensures
that progress is being made."*

**The transferable principle is that the sort key is the advice, not a metric
dump.** The key itself does not transfer: helpmates have no DTZ, no 50-move
rule, and no zeroing. What transfers with it:

- row 1 is always the recommended move, whichever side is to move;
- badges state a claim (`"Win with DTZ 12"`), never a bare number;
- a metric is **omitted** where it would mislead — a zeroing move shows
  `"Zeroing"` with no number, because after a capture the counter resets and
  the number is not comparable to its neighbours;
- categories are encoded in the domain's own colours with a **shape** for the
  qualifier (a 3px grey inset ring for a win frustrated by the 50-move rule),
  so nothing is colour-only;
- the input pane is fixed and only the answer pane scrolls.

Two of its weaknesses we will not inherit: the hard 310px column cap (right for
one board and one list, wrong for our histograms), and the absence of group
headers, which the study flagged as a newcomer cost for nothing saved.

## The move list

This is the centre of the redesign.

**Grouping.** Three groups, gap-separated, each with a counted header —
`Optimal (3)`, `Slower (7)`, `No mate (12)`:

| group | predicate | sort within group | badge |
|---|---|---|---|
| **Optimal** | `optimal` | ascending `count`, then SAN | `h#1 · unique` / `h#1 · 4 ways` |
| **Slower** | `solvable && !optimal` | ascending `dtm`, then `count`, then SAN | `h#2 · slower` |
| **No mate** | `!solvable` | SAN | `no mate` |

**Why `count` ascending is the right key inside the optimal group.** Every
optimal move leads to a child at `dtm = D − 1`, so **dtm cannot discriminate
there at all** — it is constant across the whole group. What does discriminate
is how forcing the move is: a child with one optimal continuation constrains
the rest of the solution, a child with twenty does not. That is also precisely
the property composers care about, so the ordering doubles as the advice, which
is the principle we took from syzygy.

**Saturation must not be misreported.** `count` saturates at 255. A child at
`count >= 255` renders as `255+ ways`, never `255 ways`. This matters: the
whole project treats a saturated count as "cannot be enumerated", and the UI
must not present a ceiling as a measurement.

**`count` here always means the child position's optimal-continuation count** —
the value `/v1/moves` returns for the position *after* the move, not for the
position being viewed.

**The DOM contract is preserved deliberately, and the group headers must not
break it.** Seven of the sixteen Playwright tests use
`page.wait_for_selector("#move-list li")` as their "page is ready" idiom, two
of them count `#move-list li`, and one maps `dataset.san` across every match.
So a header row must not be an `<li>` inside `#move-list` — that would corrupt
both the counts and the `data-san` map.

The structure is therefore:

```html
<div id="move-list">
  <section class="move-group">
    <h3>Optimal <span class="count">3</span></h3>
    <ul>
      <li class="optimal" data-san="Kh6">…</li>
    </ul>
  </section>
  <!-- .move-group for Slower, then No mate -->
</div>
```

`#move-list` changes from `<ul>` to `<div>`, but **`#move-list li` still
selects exactly the move rows and nothing else**, which is what every test
actually asserts on. Rows keep `data-san` and the existing `.optimal` /
`.dead` classes; the middle group adds `.slower`. Verify this claim by running
the suite before touching any test file — if a count assertion moves, the
structure is wrong, not the test.

## Layout

Syzygy's structural win without its pixel cap: **the board pane is fixed and
only the answer pane scrolls**, so a long move list never drags the board out
of view — no sticky headers, no scroll-sync JavaScript.

Ours is a fluid two-column grid with a `max-width` rather than a fixed 310px,
because we have histograms and result tables that genuinely need width. Below
the breakpoint the columns become plain blocks and stack: board, then answer.
Mobile is the default and the two-column rule is the enhancement, matching the
benchmark's `min-width: 680px` direction.

**Nothing is hidden on small screens.** Syzygy also strips chrome on short
landscape viewports via height queries; we will not, because our chrome is
already minimal and hiding controls is a support burden.

## Reference material appears only on the empty board

Syzygy renders its About / Download / Contact material **only** when the FEN is
the default. Ask a real question and the explanatory copy vanishes. We adopt
this for the explorer's primer `<details>` and legend: present on the landing
position, gone once the user has a position of their own. A published tool
should explain itself to a newcomer and then get out of the way.

## Design tokens

`app.css` is rewritten as a token system rather than 242 lines of ad-hoc
literals. Concretely:

- **A type scale.** There are currently twelve different ad-hoc rem sizes
  (`.7`, `.78`, `.8`, `.82`, `.84`, `.85`, `.86`, `.88`, `.9`, `.95`, `1.05`,
  `1.15`). Replace with a named scale of five steps.
- **A spacing scale.** `--step: .5rem` is declared and never used; every
  spacing value is a hard-coded literal. Make the scale real and use it.
- **One palette, defined once.** The dark values are currently duplicated
  three times (media query, `[data-theme="dark"]`, `[data-theme="light"]`).
- **Redundant encoding, per the benchmark.** Every state carries text as well
  as colour; the qualifier (unique vs. multiple continuations) is a ring or
  border, not a new hue. Nothing is colour-only.

### The palette is replaced, not kept

The current warm-cream ground (`#f7f5f0`) with a terracotta flag (`#a4542a`)
goes. It is not wrong for being warm — it is wrong for being *saturated*. The
replacement is **lichess's shipped theme**, read off
`ui/lib/css/theme/_theme.default.scss` / `_theme.light.scss`, whose whole
system is two rules:

1. **Grounds carry one hue**, declared once (`---site-hue: 37deg`) and derived
   for every surface, at **5–10% saturation**.
2. **Ink and rules are exactly achromatic** — hue 0, saturation 0.

Our old palette was hue 37 as well, at 30–40% saturation. That is the
difference between a tint and a colour, and cream-plus-terracotta is a
signature that now reads as machine-generated on sight.

| token | light | dark |
|---|---|---|
| `--ground` | `#edebe9` | `#161512` |
| `--panel` | `#ffffff` | `#262421` |
| `--sunk` (zebra) | `#f5f4f2` | `#33312e` |
| `--ink` | `#2b2b2b` | `#bababa` |
| `--ink-soft` | `#6b6b6b` | `#949494` |
| `--ink-faint` | `#949494` | `#787878` |
| `--rule` | `#d9d9d9` | `#404040` |
| `--accent` | `#1b78d0` | `#3692e7` |

Two arguments beyond taste. First, syzygy-tables.info's dark mode **is** this
palette — `#161512`, `#262421`, `#bababa`, `#404040`, `#3692e7` all match
lichess exactly — so adopting it makes us consistent with the nearest
neighbour tool rather than merely inspired by it. (Its *light* mode is
stock Bootstrap 3 — `#333`/`#eee`/`#ccc`/`#337ab7` — and is the one part of
syzygy not worth copying.) Second, every instrument UI surveyed picks a blue
accent in a startlingly narrow band: Primer `#0969da`, Grafana `#1f62e0`,
Datasette `#276890`, Bootstrap `#337ab7`, lichess `#1b78d0` — **hue 203–220°,
median 211°**. The discipline is not desaturation (those run 56–93% saturated)
but hue-lock plus restraint about placement. The accent is therefore confined
to links, focus rings and hover borders. It is never a field, never a header
fill, and never the move list.

Board squares are lichess's default brown (`#f0d9b5` / `#b58863`) and do
**not** change between themes.

### The ordinal is encoded without hue

Optimal → Slower → No mate is **one ranked axis, not three categories**. Three
hues is the encoding for unrelated things; a ranked scale belongs to
**luminance and weight**:

| group | encoding |
|---|---|
| Optimal | filled badge (`--ink` on `--on-ink`), 3px inset bar in the row gutter |
| Slower | outlined badge, same ink, no fill |
| No mate | faded to `--ink-faint`, SAN struck through |

This is syzygy's own device rather than an invention. It renders a five-level
win / cursed-win / draw / blessed-loss / loss scale in white, mid-grey
(`#757575`) and black — the colours of the game itself, so it needs no legend
— and marks the two degraded levels with a `3px` inset ring in the draw grey
rather than a fourth hue. Its dark mode shifts that grey to `#999999` so the
ordinal midpoint holds *relative to the ground*; ours must do the same.

Green→amber→red is the obvious move and the wrong one: **a slower move is not
a warning**, and hue-only ordinals fail exactly where adjacent levels must be
told apart. Where lichess does use hue for move quality it runs
blue→amber→red, holding green back for the *exceptional* case rather than
spending it on "fine".

The qualifier — "only reply" vs. several continuations — stays a ring on the
badge, so nothing on the page is encoded by colour alone.

Also avoided, each because something in the survey earns it: vertical
`linear-gradient` on headers and buttons (skeuomorphic residue; the
most-criticised part of lichess's own chrome); large radii with a soft drop
shadow on every card — lichess ships **7px**, Primer 6px, so ours is `6px` and
panels are border-only; and saturated violet or a neon-on-black accent, which
are simply the *next* cliché rather than an escape from this one.

**Dark mode gets a toggle.** The CSS already exists; the work is a control that
sets `data-theme` on `:root`, persists the choice, and defaults to
`prefers-color-scheme` when unset — the three-state pattern (system / light /
dark) rather than syzygy's system-only, which its own study flagged as a gap.

## Search panel

Same treatment, no new capability: the design system, the responsive grid, and
results presented as a table with the data we already have rather than a flat
list of FEN strings. The form keeps its current fields and client-side
validation.

## Testing

- **The 38 JS unit tests must stay green untouched.** They import only
  `js/api.js` and the pure `js/lib/*` modules and pin zero DOM. If a change
  requires editing them, the change is in the wrong layer.
- **The 16 Playwright tests are the redesign's contract.** Preserving the ids,
  the `data-san` / `.optimal` / `.dead` attributes, `aria-pressed`,
  `data-rows`, `data-material` and `data-panel` keeps them green. Where a test
  pins exact text that the redesign genuinely changes — the theme line's `·`
  separator, `#position-summary`'s wording — the test is updated **and the
  reason recorded in the commit**, never loosened to fit.
- **New tests are required for the sort**, because it is the feature: a
  position whose optimal moves have differing `count` must render them
  ascending; a position with all three groups must render them in order; and a
  saturated child must render `255+`, not `255`.
- Playwright already runs headless Chromium in CI, so the new cases cost no
  new infrastructure.

## Non-goals

No build step, no framework, no npm — the benchmark does drag-and-drop chess,
live probing, history and dark mode in **22.5 KB gzipped** with three HTTP
requests total, and our no-build vanilla setup is an asset worth keeping. No
new API endpoints: everything above is renderable from data `/v1/moves`,
`/v1/probe` and `/v1/line` already return. No change to the URL/hash schema, so
existing shared links keep working.

## Deferred

**Puzzle page** — guess the solving move, with difficulty levels. A genuinely
new feature and its own design problem: what makes a helpmate hard is not
obvious, though we hold exactly the data to grade it (solution count and mate
length are the two axes, and `count == 1` at longer `dtm` is the hard corner).

**Load and concurrency** — behaviour under ~30 simultaneous searches. A mining
query scans a whole plane; the current server has no queue, no cancellation
beyond the client's own, and no per-request budget. Needs measurement before
design.
