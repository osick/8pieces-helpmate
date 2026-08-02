# Theme detection (v0.8) — Design

Date: 2026-08-03
Status: approved by user (brainstorming session 2026-08-03)
Origin: `specs/specround_2026_07_29.md` — "pattern search (#solution, moves,
position, pattern, moves, themes, …)", roadmap rung v0.8.
Reference studied: the Helpmate Analyzer glossary at
<https://helpman.komtera.lt/themes.html> (Viktoras Paliulionis), which
recognises 300+ named themes. Theme names here follow its vocabulary wherever
one exists, so results are comparable with established practice.

## What this is for

**Mining is the business.** The point is not to annotate one position — the
Helpmate Analyzer already does that, and does it more deeply than this rung
will. The point is to search: *find me positions in KRvkbn at h#4 with a
unique solution that ends in a model mate.* No single-problem analyser can
answer that, because answering it means evaluating millions of candidates.
This tablebase can, and that is the capability worth building.

Annotation falls out for free — the same detectors, applied to one position —
and is exposed, but it is the by-product, not the goal.

## Scope: twelve themes, two cost classes

Chosen because each is (a) precisely definable, (b) computable from a single
optimal solution or its final position, and (c) cheap enough to run inside a
`mine` scan. Everything else waits; see **Out of scope**.

### From the mating position alone

One pass over the final board. No move history required.

**`pure`** — a pure mate. Every square of the black king's field is
unavailable to the king for **exactly one** reason:

- attacked exactly once by White and unoccupied, or
- occupied by a black unit and not attacked by White, or
- occupied by a white unit,

and the king's own square is attacked exactly once. A square that is both
occupied by a black unit *and* attacked by White is doing double duty and
breaks purity. Double check therefore makes a mate impure under this
definition.

*Contested edge, decided here:* a square attacked by a **pinned** white unit
counts as attacked. A pinned unit still controls squares for the purpose of
the black king's legality, and the alternative reading requires modelling
"would this pin actually matter", which is not decidable locally.

**`model`** — a model mate: `pure`, and every white unit on the board **except
the king and pawns** participates in the mate. A unit participates if it
attacks the king's square or any square of the king's field, or blocks such a
square by standing on it. White pawns and the white king are exempt by
convention.

**`ideal`** — an ideal mate: `model`, and **every** unit on the board of
either colour participates, with no exemptions. The white king and white pawns
must participate too, and every black unit must be blocking a field square or
pinned in a way that matters.

**`mirror`** — a mirror mate: every square of the black king's field is
**empty** — no unit of either colour stands on any square adjacent to the
black king.

### From one solution's plies

O(plies) per solution. Requires the structured solution type below.

**`promotion`** — at least one ply promotes a pawn.

**`underpromotion`** — at least one ply promotes to rook, bishop or knight.

**`excelsior`** — a pawn that stands on its own second rank at the start of the
solution promotes during it. Detected for either colour; the reported theme
records which.

**`switchback`** — a unit leaves a square and returns to it later in the same
solution, having visited **exactly one** intermediate square (an out-and-back).

**`closed-walk`** — Rundlauf. A unit returns to its departure square having
visited **two or more** distinct intermediate squares, so it traverses a
circuit rather than retracing its path. `switchback` and `closed-walk` are
mutually exclusive by construction.

**`self-block`** — a black unit other than the king moves to a square of the
black king's field, and in the mating position that square is occupied by that
unit and **not** attacked by White. The unit blocks a flight square its own
king would otherwise have used.

**`single-piece`** — every move by one side in the solution is made by the same
unit. Evaluated per side; the reported theme records which side, so
`single-piece:white` and `single-piece:black` are distinguishable. The Black
form subsumes the Analyzer's *BK moves only* when the unit is the king.

**`en-passant`** — at least one ply is an en-passant capture.

## Solution representation

`Tablebase::lines()` returns `vector<vector<string>>` — SAN text. That discards
everything a detector needs: which unit moved, from and to where, what it
captured, and the board after each ply. So the core gains a structured form:

```cpp
struct Ply {
    Piece piece;                        // what moved (colour + type)
    uint8_t from, to;
    std::optional<PieceType> captured;  // nullopt if quiet
    std::optional<PieceType> promotion;
    bool is_ep = false;
    bool is_check = false;
    Board after;                        // position after this ply
};
struct Solution {
    Board start;              // the queried position, before any ply
    std::vector<Ply> plies;   // empty when the queried position is already mate
};
```

`start` is not redundant. A position with `dtm == 0` is already mate and has an
*empty* ply vector, so without it the mate-position detectors would have no
board to read at all. `self-block` also needs the position immediately before
the blocking move, which for the first ply is `start` and thereafter is
`plies[i-1].after`.

`Tablebase::solutions(fen, max)` returns `vector<Solution>`, built by the same
walk `collect_lines` already performs. **`lines()` keeps its current signature
and behaviour** — nothing downstream changes, and the SAN path stays the
cheaper option for callers that only want text.

Carrying a whole `Board` per ply is deliberate: every mate-position detector
needs one, and helpmate solutions are short (h#8 is 16 plies). Recomputing
boards inside each detector would be both slower and more error-prone.

## Detectors

`src/core/themes/` — one file per cost class, plus a registry:

```cpp
// A detector is a pure function of a solution. No table access, no I/O,
// so every one is testable against a hand-built position with no .hm file.
using Detector = bool (*)(const Solution&);   // sees Solution::start too
struct ThemeDef { std::string_view name; Detector fn; std::string_view doc; };
const std::vector<ThemeDef>& theme_registry();
```

Adding a theme is one function and one registry entry; CLI, API and dashboard
all inherit it with no further plumbing, because each enumerates the registry
rather than hard-coding names.

Mate-position detectors take the final `Ply::after` — or `start` when the
queried position is itself the mate — and ignore the rest; line
detectors walk the whole vector. Both share the `Detector` signature so the
registry stays uniform.

## Query semantics

**`any`, not `all`.** A position matches `--theme model` when **at least one**
of its optimal solutions shows the theme. A position with four solutions of
which one ends in a model mate is a hit. This is the better discovery
primitive: `all` is a filter over hits, and can be added later as
`--theme-all` without changing the default.

**Multiple themes AND.** `--theme model --theme excelsior` requires both, but
not necessarily in the same solution. A same-solution variant is deliberately
not offered in v0.8 — it is a distinct and less-obvious query, and offering it
before anyone has asked risks guessing wrong.

**Saturated positions are skipped, not guessed at.** When a position's optimal
line count is `COUNT_SAT` (255), its solutions cannot be enumerated in full;
`SolutionShape::exhaustive` already reports this and `mine` already counts such
positions in `skipped_saturated`. Theme filters reuse that mechanism exactly —
a saturated position never matches a theme filter, and is reported in the
skipped tally rather than silently dropped.

**The solution cap is a known false-negative source.** `solutions(fen, max)`
caps enumeration (100 by default, as `lines()` does today). Under `any`
semantics a theme present only in solution 101 is missed. This is documented
rather than fixed: raising the cap is a flag, and the alternative — unbounded
enumeration on positions with hundreds of solutions — is worse.

## Surfaces

**CLI**

```
helpmate mine <MATERIAL> --dtm N [--theme NAME]...   # repeatable, AND
helpmate probe <FEN> --themes                        # annotate one position
helpmate themes                                      # list detectors + docs
```

`helpmate themes` prints the registry, so the vocabulary is discoverable
without the docs.

**API**

- `GET /v1/mine?...&theme=model&theme=excelsior` — repeatable parameter,
  validated against the registry; an unknown name is a 400 `invalid_theme`
  listing the valid ones, never silently ignored.
- `GET /v1/probe?fen=…` gains a `themes` array in its response.
- `GET /v1/themes` — the registry, for the dashboard to build its own UI
  without a hard-coded list.

**Dashboard**

Search panel gains a theme multi-select, populated from `/v1/themes`. Explorer
shows the current position's themes in the position summary, beside dtm and
count.

## Performance

Theme filters force solution enumeration for every candidate that passes the
dtm/count filters — the same work `--starts`/`--ends` already do, so the cost
class is not new. It is nonetheless materially slower than a plain `--dtm`
scan, and on **block-compressed** tables it compounds with the ~6.5× mining
penalty measured in v0.7.5, since solution enumeration is exactly the random-
access pattern that defeats the block cache.

Consequence to document, not to engineer around yet: mine against raw tables
when running theme searches over large material.

**No precomputed index, and no new file format.** Themes are computed during
the scan. This is the deliberate simplification: definitions will change as
they are argued with, and an index would need regenerating across 89.7 GB
every time one did. If profiling later justifies an index, the detectors are
already pure functions and nothing about them would need to change.

## Verification

Each detector ships with hand-built positions asserting both directions —
a position that shows the theme and a near-miss that does not. Near-misses
matter more than positives: a `pure` detector that ignores the double-duty
rule passes every positive case.

The golden `KQvk` position (`8/7k/5K2/8/8/8/8/6Q1 b - - 0 1`, dtm 2, count 4,
four known solutions) is used where applicable, since its solutions are
already pinned by tests across the C++, Python and CLI suites.

Reference positions from published problems, and cross-checking against the
Helpmate Analyzer, are **deferred by explicit decision**. The definitions above
are stated precisely enough to be argued with, which is the prerequisite for
that work rather than a substitute for it. The risk is accepted and recorded:
a detector whose definition is subtly at odds with composition convention will
return confident wrong results, and no test here will catch it.

## Out of scope, with reasons

**Cross-solution themes** — *Echo mates*, *Chameleon echo-mates*, *Zilahi* and
variants, *Allumwandlung* (which normally spans solutions), *Mates on same
square*, *Place exchange*, the cyclic and exchange-of-function families. These
need every solution compared against every other, and several need geometric
congruence between mating positions. Natural next rung, and the one where this
project's exhaustive solution data is uniquely valuable.

**Geometric patterns** — *Star*, *Big star*, *Cross*, *Knight wheel*,
*Rosette*, *Staircase*, *Zigzag*, *Wigwag*, *Pendulum*. Initially grouped with
the cheap themes; that was wrong. They need one unit to make four or more moves
in a recognisable shape, which within a single solution of at most sixteen
plies is rare. In practice they are realised across a problem's solutions,
which makes them cross-solution work.

**Castling-dependent themes** — *Castling*, *Uncastling*, *Artificial
castling*, *Valladao task*. Permanently impossible: the table format never
supports castling rights, by design (`docs/USAGE.md`, "Scope and rules"). En
passant *is* supported, so ep-dependent themes are available.

**Twins and set play** — possible, and cheaper here than in a single-problem
analyser, but out of scope for v0.8. Set play is the same position with the
other side to move, which the tables already store as the second plane. Twins
are transformations of a position, most of which land in the same table or one
already generated. Both need their own vocabulary of transformations and their
own rung; the tablebase makes them tractable rather than trivial.

**Composer-named themes** — *Abdurahmanovic*, *Azemmour*, *Onkoud*, *Sabra* and
the rest. Complex specified patterns, each its own project.

## Risks

- **Definitional drift.** The precise wordings above are this project's
  choices. Where convention differs, the code follows the spec and the spec is
  the thing to argue with. Every detector's doc string carries its definition
  so a disagreement is visible from `helpmate themes`.
- **False negatives from the solution cap**, as described under Query
  semantics. Documented, not silently absorbed.
- **Compounding cost on compressed tables**, as described under Performance.
- **`pure` is the hardest of the twelve** and the one most likely to be subtly
  wrong: it drives `model` and `ideal`, so an error there propagates to three
  detectors. It gets the most near-miss test cases.
