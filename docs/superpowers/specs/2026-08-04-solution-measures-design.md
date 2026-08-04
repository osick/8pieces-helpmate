# Solution measures (v0.8.5) — Design

Date: 2026-08-04
Status: drafted from user requirements of 2026-08-04; awaiting review
Origin: user request — count promotions (per side), match a promotion multiset
(`Q,B,B,R`), count captures (especially **zero**).
Depends on: v0.8.0's `Solution`/`Ply` types. Nothing else.

## The distinction this rung rests on

`mine` already has two kinds of filter and they are not the same thing:

- **Measures** — `--dtm`, `--count`, `--starts`, `--ends`. Parametric: each
  carries a value, and the value is the question.
- **Themes** — `--theme model`, `--theme en-passant`. Boolean and nameable.

The three capabilities requested here are **measures**, not themes, and this
spec exists mostly to say so. Encoding "three promotions" as a theme would
need one registry entry per value (`promotions:0`, `promotions:1`, …), and the
promotion-multiset case is combinatorially hopeless — there are hundreds of
multisets over {Q,R,B,N} before you reach four promotions. Measures take a
value; themes take a name. Keeping them apart keeps both surfaces small.

**Nothing new is needed to compute them.** `Ply` already carries `captured`,
`promotion` and the mover's colour. Every measure below is a pure function of
a `Solution`, exactly like a detector, differing only in return type.

## The measures

### Promotion count

```
--promotions N          promotions by either side
--promotions-white N    promotions by White
--promotions-black N    promotions by Black
```

Exact match, consistent with every existing filter. `--promotions 0` is a
real query (a solution that reaches mate with pawns present and none
promoting) and must be distinguishable from "not filtering", so the sentinel
for "not given" is -1, as `--count`/`--starts`/`--ends` already do.

### Promotion multiset

```
--promotion-set QBBR         the solution's promotions are exactly this multiset
--promotion-set-white QR
--promotion-set-black BN
```

Order-independent: `QBBR`, `BQRB` and `RBBQ` are the same query. Case
-insensitive on input, normalised for comparison. Pieces are `Q`, `R`, `B`,
`N`; a pawn cannot promote to a king or a pawn, so any other letter is a
usage error naming the four valid ones.

`--promotion-set` implies its own count, so combining it with `--promotions`
is redundant but not an error — unless the two disagree, which **is** an
error rather than a silently empty result.

*Contested edge, decided here.* `--promotion-set QRBN` is **not** the same
question as Allumwandlung. The Helpmate Analyzer glossary defines AUW as *"the
four possible types of promotion all take place during the course of the
solution"* — a **set-coverage** condition, so `QRBNN` is also an AUW. The flag
above is an **exact multiset**, so `QRBNN` does not match `QRBN`. Both are
useful and they are different: the flag answers "exactly these promotions",
the theme answers "at least one of each". AUW therefore stays a boolean theme
(catalogue tier B) and is **not** replaced by this flag.

### Capture count

```
--captures N          captures by either side
--captures-white N    captures made BY White
--captures-black N    captures made BY Black
```

**`--captures-white` counts captures *made by* White, not white units
captured.** The alternative reading is the one Zilahi cares about, and it is a
genuinely useful measure, but it is a different measure; naming this one by
mover keeps it consistent with `--promotions-white`, which can only sensibly
mean "promotions made by White". If the captured-colour reading is wanted
later it gets its own name (`--losses-white`), never a redefinition of this
one.

En-passant captures count as captures. `Ply::captured` is set for them (the
victim is a pawn not standing on the destination square, which
`collect_solutions` already handles).

`--captures 0` is the flagship query of this rung: a solution that reaches
mate without a single capture is a recognised compositional virtue and there
is currently no way to ask for one.

## Semantics

**`any` over solutions, matching themes exactly.** A position matches
`--captures 0` when **at least one** of its optimal solutions has zero
captures. This is deliberate and it is the same rule `--theme` uses: `any` is
the discovery primitive, and "every solution" is a filter over hits that can
be added later without changing the default.

Note the consequence plainly: `--captures 0` does **not** mean "this position
has no capturing solutions". It means one solution is capture-free. For a
composer chasing a clean unique problem the useful query is
`--captures 0 --count 1`, and the docs must say so.

**Measures AND with each other and with themes.** `--captures 0 --promotions 2
--theme model` requires all three, but — as with multiple `--theme` flags —
not necessarily in the same solution. Same-solution conjunction remains
unavailable, and this rung does not add it.

**Saturated positions never match**, via the existing mechanism. A position
whose optimal-line count is 255+ cannot be enumerated, so it cannot match any
measure, and it is reported in `skipped_saturated` rather than dropped
silently. No new code: the guard already sits in front of enumeration.

## Architecture

`src/core/themes/measures.h` — pure functions beside the detectors:

```cpp
namespace hm::themes {
// nullopt for `colour` means either side.
int promotion_count(const Solution&, std::optional<Color> = std::nullopt);
int capture_count(const Solution&, std::optional<Color> = std::nullopt);
// Promotion pieces in ply order; the caller sorts to compare as a multiset.
std::vector<PieceType> promotion_pieces(const Solution&,
                                        std::optional<Color> = std::nullopt);
}
```

`MineFilter` gains the fields, each -1 / empty for "not given":

```cpp
int promotions = -1, promotions_white = -1, promotions_black = -1;
int captures   = -1, captures_white   = -1, captures_black   = -1;
std::string promotion_set, promotion_set_white, promotion_set_black;
```

Nine fields is a lot, and it is the point at which the flag-per-measure
pattern starts to strain. It is still the right choice **now**: each flag is
explicit, greppable and obvious, and matches the surface users already know.
The moment a fourth measure family arrives (checks, quiet moves, trajectory
length), convert the whole surface to one expression flag rather than adding
three more. That conversion is a deliberate later decision, recorded here so
it is not made by accident.

`mine` already enumerates solutions once for shape and theme filters; measures
are evaluated from that same `std::vector<Solution>`. **No extra enumeration
and therefore no measurable cost** — the enumeration is the expense, as the
v0.8 measurements established, and these are arithmetic over data already in
hand.

## Surfaces

**CLI** — the nine flags above on `mine`. `probe` gains `--measures`, printing
the counts and promotion multiset for the queried position, beside
`--themes`. Unknown values remain a loud usage error, exit 3, never silently
dropped.

**API** — the same nine as query parameters on `/v1/mine`. An invalid
promotion-set letter is a 400 `invalid_promotion_set` naming `Q`, `R`, `B`,
`N`. `/v1/probe?measures=true` mirrors the CLI, opt-in for the same reason
themes are: it forces enumeration on the dashboard's hot path.

**Dashboard** — numeric inputs beside the existing `count`/`starts`/`ends`
fields, and a short text input for the promotion set. No new panel.

## Verification

Each measure gets both directions on hand-built solutions — a positive and a
near-miss — as the detectors do. Beyond that, three specific cases that
existing fixtures cannot reach:

- **En passant counts as a capture.** The `KPvkp` position
  `8/p7/8/1P6/8/8/8/k1K5 b - - 0 1` has the optimal line
  `a5 bxa6 Ka2 a7 Ka1 a8=R#` — verified during the v0.8 work. Its capture
  count must be 1, not 0.
- **Multiset order-independence.** The `KPvkp` position
  `8/3p4/8/8/1P6/8/8/K1k5 b - - 0 1` has solutions promoting `b8=Q`+`d1=B`,
  `b8=Q`+`d1=R` and `b8=Q`+`d1=Q` — verified. `--promotion-set BQ` and
  `--promotion-set QB` must both match it, and `--promotion-set QQ` must match
  it too, via the third solution.
- **`--promotion-set QRBN` is not AUW.** A test pins that a solution promoting
  `Q,R,B,N,N` fails the exact-multiset query while satisfying set coverage.

The `--captures 0` path needs a real hit on a real table to be trusted, not
only a hand-built solution; the plan must produce one and record it.

## Out of scope

Ranges (`--captures 0-2`) — every existing filter is exact, and mixing would
need a syntax decision that belongs with the expression-flag conversion above.
Same-solution conjunction. The captured-colour reading of `--captures-white`.
Any new theme: AUW, Zilahi and the rest of catalogue tier B are a separate
rung and are not started here.

## Risks

- **`any` semantics will surprise someone on `--captures 0`.** It reads as a
  property of the position and is a property of one solution. Documented in
  the flag's own help text, not only in `USAGE.md`.
- **Nine flags.** Recorded above with the trigger for converting them.
- **`--promotion-set` and `--promotions` can contradict.** Made an explicit
  error rather than an empty result, so a contradictory query is never
  mistaken for "nothing matches".
