# `mine` starts/ends filters (v0.6.2) — Design

Date: 2026-07-31
Status: approved by user (brainstorming session 2026-07-31)
Origin: user request — filtering by the number of distinct starting and mating
moves is "an enormous help when searching for good helpmates". Last release
before the web dashboard.

## Goal

Let `helpmate mine` and `GET /v1/mine` select positions by the *shape* of their
solution set, not only its size: how many distinct moves the solutions begin
with, and how many distinct moves they mate with.

## Semantics

For a position whose optimal solutions are enumerable:

- **starts** = the number of distinct **first moves** across all optimal lines
  (Black's opening move, since Black moves first in a helpmate).
- **ends** = the number of distinct **final moves** across all optimal lines
  (the mating move).

Moves are compared as SAN strings, which identify a move uniquely within a
given position.

`--starts N` matches when starts == N exactly, `--ends N` when ends == N
exactly — consistent with `--dtm` and `--count`, which already match exactly.
Both flags are optional and independent; when both are given, both must hold.

Worked example, verified against the project's golden position
`8/7k/5K2/8/8/8/8/6Q1 b - - 0 1` (KQvk, dtm 2, count 4). Its four optimal
lines are `Kh6 Qh2#`, `Kh6 Qh1#`, `Kh6 Qg6#`, `Kh8 Qg7#`, so **starts = 2**
(`Kh6`, `Kh8`) and **ends = 4** (`Qg6#`, `Qg7#`, `Qh1#`, `Qh2#`). It matches
`--starts 2 --ends 4` and is rejected by any other value.

Why this helps composition search: `--count 4 --starts 1` finds positions whose
four solutions all begin with the same move; `--count 2 --ends 1` finds two
solutions converging on one mate.

## Validation

- `--starts N` / `--ends N` require `N >= 1`.
- When `--count C` is also given, both require `N <= C`: a position with C
  optimal solutions cannot have more than C distinct first or final moves. A
  violating combination is a usage error (CLI exit 3, HTTP 400), not a silently
  empty result.
- `--max` is unchanged: it caps how many result rows are returned.

## The saturated-count limitation (explicit, not hidden)

The stored optimal-line count saturates at 255, meaning "255 or more". For such
a position the solution set cannot be enumerated exhaustively, so its true
starts/ends values are unknowable from the table. Those positions are
**skipped** whenever `--starts` or `--ends` is in play, and the count of skipped
positions is reported — CLI on stderr, API as a `skipped_saturated` field in the
JSON. Silently omitting them would misrepresent coverage. Positions with
non-saturated counts are unaffected, which is every case of practical interest
for composition work.

## Components

### 1. `MineFilter` (`src/probe/tablebase.h`)

```cpp
struct MineFilter {
    int dtm    = -1;   // required, exact
    int count  = -1;   // optional, exact
    int starts = -1;   // optional, exact
    int ends   = -1;   // optional, exact
};
```

`Tablebase::mine` takes a `MineFilter` instead of `(dtm, count)`. The dashboard
will want further filters (themes, piece placement); a struct gives them a home
without changing the signature again. The only callers today are the CLI and
the Python binding, both updated in the same change.

### 2. Solution-shape evaluation (`src/probe/tablebase.cpp`)

A single function computes the shape of a position's solution set:

```cpp
struct SolutionShape { int starts; int ends; bool exhaustive; };
SolutionShape solution_shape(const std::string& fen) const;
```

It enumerates optimal lines via the existing `lines()` machinery, then counts
distinct first and last elements. `exhaustive` is false when the stored count is
saturated — the caller (mine) then skips the position and increments its skipped
tally. Keeping this separate from `mine`'s scanning loop makes it unit-testable
against known positions without generating anything.

Cost: computed only when `starts` or `ends` is requested, and only for positions
that already passed the cheap `dtm`/`count` filters, so the scan cost of an
unfiltered `mine` is unchanged.

### 3. Surfaces

- **CLI** (`src/cli/main.cpp`): `--starts N`, `--ends N` parsed with the
  existing `parse_int` helper, documented in the usage text with an example;
  skipped-position tally printed to stderr when non-zero (stdout stays a clean
  FEN list).
- **HTTP** (`server/helpmate_server/app.py`): `starts` and `ends` query
  parameters on `/v1/mine`, validated identically, errors through the existing
  envelope; response gains `skipped_saturated: <int>`.
- **Python** (`src/bindings/pymodule.cpp`, `python/helpmate/__init__.py`):
  `mine(material, dtm, count=-1, max=100, starts=-1, ends=-1)` — additive
  keyword arguments with defaults, so existing calls are unaffected.

## Performance (measured, 2026-07-31)

The filters are query-side only. Measured on a generated KQvk closure:

| Path | Effect |
|---|---|
| generation (`gen`) | zero — no generator code changes, no format change, nothing stored |
| `probe` / `line` / `lines` | zero — untouched |
| `mine` without the new flags | zero — 2000 hits scanned in 3 ms, unchanged path |
| `mine` with the new flags | ~107 us per candidate that already passed `dtm`/`count` (213 ms for 2000) |

The added cost is inherent — the distinct first moves cannot be known without
enumerating the solutions — and is paid only for positions that already matched
the cheap filters. Shape distribution over those 2000 positions, showing the
filter discriminates usefully: (1,1) 515, (1,2) 400, (2,1) 263, (2,2) 209,
(2,3) 155, (3,2) 53.

## Format-version diagnostics (small, included)

Discovered while measuring: a pre-v0.6.1 binary reading a compacted directory
reports `no table for X`. `TableReader::open` returns `nullopt` for a file it
cannot parse — including one whose format version it does not know — and the
probe layer cannot distinguish that from an absent file. After v0.6.1's
marker tables this is a live scenario for anyone with a mixed installation
(an old server process, a stale Python extension).

Fix, in this release: `open` distinguishes "not present" from "present but
unreadable by this build". When a file exists with a valid `HM8P` magic but an
unsupported version or flag combination, the probe/generator layers surface
`table <path> was written in format version <N>; this build supports up to
<M> — upgrade helpmate` instead of reporting the table as missing. Tested with
a hand-crafted future-version header.

## Testing

- **Unit** — `solution_shape` against the golden KQvk position (expect
  starts 2, ends 4, exhaustive true) and a dtm-1 position (starts 1, ends 1);
  `MineFilter` matching logic for each combination of set/unset fields.
- **CLI** — `mine --starts 2 --ends 4` returns the golden position;
  `--starts 3` (same query) returns nothing; `--starts 5 --count 4` exits 3
  with a clear message; `--starts 0` exits 3.
- **API** — the same three cases through `/v1/mine`, including the 400 envelope
  and the `skipped_saturated` field's presence.
- **Python** — a smoke test that the new keywords filter as expected and that
  omitting them reproduces today's results exactly.
- **Regression** — existing mine tests must pass unchanged, proving the
  `MineFilter` refactor is behaviour-preserving.

## Out of scope

Range or inequality matching (`--starts 2-4`, `--starts >=2`); filtering by
which specific moves start or end the solutions; theme detection. If range
matching is wanted later it extends `MineFilter` without disturbing this design.
