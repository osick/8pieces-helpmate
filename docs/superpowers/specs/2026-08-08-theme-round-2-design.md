# Theme detection, round 2 — Design

Date: 2026-08-08
Status: **approved by the user** (brainstorming session of 2026-08-08).
Origin: theme selection against `docs/THEME-SELECTION.md`, which regroups the
295 catalogued themes by the machinery each needs.

Scope: **seven boolean themes**, plus the one structural change two of them
require. Parametric themes were explicitly deferred — see *Deferred* below.

## What changes and why

v0.8.0 defined a detector as a pure function of one `Solution`
(`registry.h`), with `any`-across-solutions applied by the caller. Two of the
seven themes do not fit that shape:

- **`homebase`** is a property of the diagram. It needs no solutions at all.
- **`set-play`** is a property of the *other side-to-move plane*. It needs a
  table lookup, which a detector is forbidden to do — and rightly: purity is
  what lets every detector be tested against a hand-built position with no
  `.hm` file on disk.

The resolution is to pass detectors the **values** they need rather than the
means to fetch them. Purity is preserved; the caller does the fetching.

```cpp
enum class Needs : uint8_t { Position, Plane, Solutions };

struct ThemeInput {
    const Board& start;                     // the diagram, always present
    std::optional<ValuePair> other_plane;   // same position, other side to move
    const std::vector<Solution>& solutions; // empty unless needs == Solutions
};

using Detector = bool (*)(const ThemeInput&);
struct ThemeDef { std::string_view name; Detector fn; std::string_view doc; Needs needs; };
```

> **v0.9.1 update:** `ThemeInput` gained a fourth field, `ValuePair value` —
> this position's own stored dtm/count, alongside `other_plane`, the sibling's
> value — because `set-play`'s shipped definition turned out to be a bug (see
> the "Three definition decisions worth arguing with" section below, revised
> for the fix). Both production construction sites (`Tablebase::mine`'s scan
> loop and `Tablebase::themes_of`) were updated to supply it.

The existing sixteen entries keep their bodies untouched and are registered
through a wrapper that supplies the `any`:

```cpp
template <bool (*F)(const Solution&)>
bool any_of(const ThemeInput& in) {
    for (const auto& s : in.solutions) if (F(s)) return true;
    return false;
}
```

**This removes a special case rather than adding machinery.** Today `any`
lives in two places — `detect()` and `mine` — and a theme that is not
per-solution has nowhere to live at all. After the change there is one
signature and one place the `any` is expressed.

### `needs` is the user-visible win

`mine` currently sets `want_solutions = want_shape || !dets.empty()`, so **any**
theme forces enumeration. Enumeration is the entire cost of theme mining
(measured: ~10.7× a plain `--dtm` scan, while the detectors themselves are
~5% of it), and it is *impossible* for the ~65% of 6-piece cells whose
solution count saturates at 255 — those positions are skipped and counted, so
a theme query silently never sees them.

With `needs`, a query whose themes are all `Position` or `Plane` skips
enumeration entirely. `mine --theme homebase` then runs at scan speed **and
answers on saturated positions**. That is a capability difference, not a
speed-up: those positions are currently unanswerable for every theme.

## The seven themes

Definitions are **this project's own**, stated precisely enough to be argued
with. As in v0.8.0 they are *not* validated against published problems or
against the Helpmate Analyzer; a detector subtly at odds with composition
convention will return a confident, wrong result.

| name | needs | definition |
|---|---|---|
| `set-play` | Plane | The same position with the **other** side to move is solvable at exactly `dtm = D - 1`, where `D` is this position's own stored dtm. **(Revised in v0.9.1 — see below; originally shipped in v0.9.0 as "solvable, full stop", which was a bug.)** |
| `kniest` | Solutions | Some ply captures on square *S*, and in the final position the mated black king stands on *S*. |
| `phoenix` | Solutions | Some ply captures a unit of type *T* ∈ {Q,R,B,N} belonging to side *C*, and a later ply promotes a pawn of side *C* to type *T*. |
| `schnoebelen` | Solutions | Some ply promotes to a unit on square *S*; a later ply captures on *S*; and no ply in between moves a unit **from** *S*. The promoted unit is captured without ever having moved. |
| `zajic` | Solutions | Some ply captures on square *S*, a later ply recaptures on *S* with the black king, and *S* is the square the black king stands on in the final position. |
| `pendulum` | Solutions | One unit's trajectory visits exactly two distinct squares and has length ≥ 4 — i.e. *A,B,A,B…*, at least two returns. |

**`homebase` was implemented against this design, then removed by the branch
review before release.** It read "every unit stands on the square it occupies
in the initial game array for its own colour and type" from the diagram
alone — cheap, and exactly the kind of `Needs::Position` theme this design
set out to make possible. What this design did not check: `mine`'s index
quotients positions by a symmetry group (`src/core/indexing/kk.cpp` confines
the White king to files a-d; `slice_index.cpp` decodes with no inverse
transform), so a cell stores an *equivalence class*, not a position. The file
mirror in that group maps the king's e-file to d and the queen's d-file to e
— `homebase` is not invariant under it, so its answer depends on which
representative you decoded, and in practice `mine --theme homebase` returned
zero rows on every material tried. `probe --themes` was unaffected (it
evaluates the exact FEN supplied, never a canonicalised one), which is what
let the bug hide behind a working example during design and review.
**The durable lesson, worth keeping even though the theme is gone: a
`Needs::Position` theme must be invariant under the index's symmetry group,
or `mine` cannot answer it correctly, however cheap the diagram read is.**
`set-play` (`Needs::Plane`) and every `Needs::Solutions` theme in this round
were checked against that constraint and are invariant.

### Three definition decisions worth arguing with

**`set-play` was shipped in v0.9.0 defined as solvability of the other plane,
full stop — this was a bug, fixed in v0.9.1.** "Solvable, full stop" is
nearly vacuous (it matched 423 of 580, 72.9%, `KQvk --dtm 2` positions) and
conflates two opposite things: a sibling solvable one move *sooner* (the mate
is already available; the side to move merely delays it — this is set play)
and a sibling solvable one move *longer* (flipping the side to move makes the
mate take longer — the opposite of set play, but the "full stop" definition
reported it as a match anyway). Parity forces the sibling to `D - 1` or
`D + 1`, never `D`.

**As of v0.9.1, `set-play` means the sibling plane is solvable at exactly
`dtm = D - 1`**, where `D` is this position's own stored dtm — which is why
`ThemeInput` had to gain the `value` field noted above; comparing only the
sibling's bare solvability cannot express "one move sooner than *this*
position." On the same `KQvk --dtm 2` query this drops the match count from
423 to 183 (31.6%). The looser "solvable at any shorter distance" reading —
not just exactly one move sooner — is a genuinely separate theme, which the
glossary distinguishes as *Short set play*; that remains unimplemented, and
is not what "D - 1" above means.

Mechanically it is as cheap as it sounds, and that is the point of the theme:
a cell index is independent of side to move (side to move selects the
*plane*, not the index), so the other plane's value for a position `mine` is
already scanning is the **same cell in the sibling plane** — one extra byte,
fetched by the read the scan is already doing. For `probe`, it is one ordinary
lookup of the same position with the side to move flipped. No search, no
enumeration, and nothing a searching analyser gets for free.

**`pendulum` overlaps `switchback` by construction.** A trajectory *A,B,A,B*
contains *A,B,A*, so every pendulum is also a switchback under the shipped
definition. They are **not** made exclusive: a position that shows both should
report both, exactly as `ideal` implies `model` implies `pure` already does.
The `closed-walk` bug of v0.8 — where the detector fired on retracing paths —
came from *not* stating an overlap rule, so it is stated here.

## Surfaces

Everything flows from the registry, so no surface learns a theme name.

- **CLI** — `helpmate themes` gains a `needs` line per entry, so a user can
  see which themes answer on saturated positions. `mine`/`probe --themes`
  unchanged in syntax.
- **API** — `/v1/themes` entries gain `"needs": "position"|"plane"|"solutions"`.
  `theme=` on `/v1/mine` is unchanged.
- **Dashboard** — the theme multi-select is already populated from
  `/v1/themes`; it marks entries that do not require enumeration. No
  theme-specific code.
- **Python bindings** — `helpmate.themes()` gains `needs` in each dict.

`probe --themes` keeps its existing limitation: a colour-flipped probe reports
themes as unavailable, because every detector is written against the black
king.

## Verification

The lesson of v0.8.0 is recorded and applies unchanged: **nothing was caught
by writing a check — everything was caught by running it or deliberately
trying to break it.** Twenty hand-authored fixtures were wrong, three detector
branches survived deletion with the suite green, and two mutations survived
inversion.

- Every fixture FEN is verified by probing it, not by reading it. A fixture
  that is not the position its comment claims is the default failure mode.
- Each detector must fail when its central branch is deleted **and** when its
  condition is inverted. Both checks are run explicitly, not assumed.
- `homebase` and `set-play` need a test that `mine` does **not** enumerate for
  them: a saturated position must be returned, where every existing theme
  skips it. That test is the whole point of `needs` and is the one most likely
  to be forgotten.
- The sixteen existing themes must produce byte-identical `mine` output before
  and after the signature change, on a real table, for every one of them.
  This is the central correctness claim of the refactor.
- `set-play` needs a table, so its tests use a generated fixture table rather
  than a hand-built board — the one theme that cannot follow the established
  pattern.

## Deferred

**Parametric themes**, explicitly, to their own round: `promotions:qrbn`
(coverage semantics — all four types occur, so `QRBNN` is an Allumwandlung),
`mating-square:e8`, `mating-piece:q`, with `allumwandlung` as an alias. The
`:` separator already carries colour variants (`excelsior:white`), so the
syntax extends the existing grammar, and `/v1/themes` would gain a
`parameter` field so the dashboard renders an input rather than a checkbox
without knowing anything theme-specific. `--theme promotion:qrbn` — the
singular typo — must be a hard error naming the plural, never a silent match
on the boolean `promotion` with the parameter discarded.

Two decisions already made there, so they are not re-argued: promotion
**coverage**, not exact multiset; and the union taken **across the whole
solution set**, since a single solution with four promotions effectively
cannot occur at seven pieces or fewer, and because mixed colours across
different solutions (black rook and white knight in one, black bishop and
white queen in another) are a genuine Allumwandlung.

Also deferred: `mating-piece` and `mating-square` as booleans (they are only
useful parameterised); the other 58 tier-B themes, which the unified signature
now makes reachable; and everything in tiers C, D and E.

## Out of scope

Validating any definition against published problems — deferred by explicit
decision in v0.8.0 and not revisited. Colour variants of the new themes. Any
change to the `.hm` format, to `mine`'s flags, or to the saturated-position
rule for themes that genuinely need enumeration.
