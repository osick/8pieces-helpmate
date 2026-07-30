# Using helpmate

The `helpmate` CLI and Python API in detail: generating tables, probing
positions, listing optimal lines, reading statistics, mining for composition
candidates — plus the exact DTM semantics, the `stats.json` field reference,
and resource guidance per piece count.

All CLI examples below are real outputs, reproduced from this repository's
test suite and README (the `8/7k/5K2/8/8/8/8/6Q1 b - - 0 1` position is the
project's golden test case).

## Concepts

### DTM semantics (plies, h#n notation)

- **dtm** is the distance to mate in **half-moves (plies)**, assuming both
  sides cooperate optimally. In a helpmate, Black moves first and helps White
  deliver mate.
- A Black-to-move position always has **even** dtm; a White-to-move position
  always has **odd** dtm (mate is a Black-to-move position with dtm 0).
- Composer notation is derived directly from dtm: a Black-to-move position
  with `dtm = 2n` is **h#n** (n Black moves + n White moves); a White-to-move
  position with `dtm = 2n+1` is **h#n.5** (White needs one extra half-move to
  deliver the actual mate). So `h#n` corresponds to `2n` plies.
- **count** is the number of *distinct* optimal lines that reach mate in the
  minimal number of plies, saturating at 255 (a stored 255 means "255 or
  more"). `count = 1` means a unique solution — what composers need for a
  sound problem; 2+ means duals.
- The byte value **255** in the tables is a sentinel for
  unsolvable/invalid cells; a slice whose *every* position is unsolvable
  (e.g. `Kvk`) reports `max_dtm=255`.

### Material names

A material string lists White's pieces in uppercase, then `v`, then Black's in
lowercase, using the letters `K Q R B N P` — e.g. `KQvk` (White king + queen
vs black king), `KBNvkq`, `KNvkqr`. Rules:

- exactly one `K` and one `k` are required;
- canonical order within each side is K, Q, R, B, N, P (the parser accepts any
  order and canonicalizes; generated files always use the canonical name);
- any combination of the six piece types, 2-8 pieces total, is accepted by the
  format (see [Resource guidance](#resource-guidance) for what is *practical*).

### Scope and rules

- **Castling is never supported**: any FEN must have `-` in the castling
  field; no FEN with castling rights is read or written.
- **En passant is exact** but not indexed: EP-dependent values are folded in
  as `min(table value, 1 + value of the EP-capture successor)` at generation
  and probe time.
- **Underpromotions are fully supported** (promotions to Q, R, B, N are all
  searched).
- The 50-move rule is ignored (irrelevant to a cooperative shortest path).

### Symmetry reduction

Positions are indexed in a symmetry-reduced dense plane. Both kings index
jointly through a precomputed non-adjacent-kings table: **462** king-pair
classes for pawnless material (full 8-fold board symmetry; White king confined
to the a1-d1-d4 triangle) and **1806** for material with pawns (left-right
mirror symmetry only, since pawns break diagonal symmetry). Every further
piece multiplies the plane by 64 (48 for a pawn — ranks 2-7 only). One
consequence: the index bakes in "White delivers mate", so probing a position
where *Black* is the mating side (e.g. `KvkQ` when only `KQvk` was generated)
is answered through an automatic **color flip** (see `probe` below).

## Getting the binary

Build per [BUILD.md](BUILD.md); the CLI lands at `./build/helpmate`. Running
`helpmate --help` prints the full usage text, every flag, and the exit codes.

Common options (all subcommands): `--tables DIR` — the table directory
(default `tables`).

## `gen` — generate tables

```
helpmate gen <MATERIAL> [--tables DIR] [--threads N] [--verbose] [--progress] [--force-ram]
```

- `--threads N`: worker threads for generation (default 1). Multithreaded
  output is byte-identical to single-threaded output (enforced by tests).
- `--verbose`: per-slice lifecycle reporting on **stderr** (stdout stays
  scriptable): the closure summary (which slices, how many are missing, the
  largest missing slice with its cell count and estimated RAM vs. what is
  available), then per slice either `cached <name> (already on disk)` or
  `generating <name> (N cells)...` / `done <name> (max_dtm=D, T seconds)`.
  Implies `--progress`.
- `--progress`: per-pass progress lines on stderr while a slice is being
  generated: the init pass, every scan pass (`pass d=K resolved M cells
  (S s)`), and every count-sweep depth, each with its wall time. Reported only
  at pass boundaries from the coordinating thread, so it adds no per-cell
  overhead; useful on its own when `--verbose`'s lifecycle lines are too chatty
  for a script but you still want a heartbeat during multi-hour 5-6 piece
  passes.
- `--force-ram`: override the RAM guard. By default `gen` estimates, before
  allocating anything, the memory each missing slice needs (4 one-byte planes
  x plane size) and compares it against `MemAvailable` from `/proc/meminfo`
  (the whole closure is costed upfront, so a hopeless 7-8 piece run fails
  immediately, not after days of sub-slice generation). If a slice does not
  fit, `gen` aborts with the slice name and both sizes in GiB; `--force-ram`
  proceeds anyway (e.g. when you trust swap to absorb it). On systems without
  a readable `/proc/meminfo` the guard is skipped.

Example (real output; all reporting lines on stderr, the two `.hm` result
lines on stdout as before):

```
$ helpmate gen KRvk --tables tt --threads 2 --verbose
gen KRvk: closure has 2 slice(s): Kvk KRvk
gen KRvk: 2 slice(s) to build; largest KRvk (29568 cells, ~0.00 GiB RAM; 54.16 GiB available)
generating Kvk (462 cells)...
  Kvk: init pass done (0.0 s)
  Kvk: pass d=1 resolved 0 cells (0.0 s)
  Kvk: pass d=2 resolved 0 cells (0.0 s)
done Kvk (max_dtm=255, 0.0 seconds)
generating KRvk (29568 cells)...
  KRvk: init pass done (0.0 s)
  KRvk: pass d=1 resolved 189 cells (0.1 s)
  ...
  KRvk: count sweep d=14/14 done (0.0 s)
done KRvk (max_dtm=14, 0.4 seconds)
tt/Kvk.hm max_dtm=255
tt/KRvk.hm max_dtm=14
```

And the guard refusing a slice that cannot fit (here a 7-piece root on a
64 GB machine; exit code 3, nothing was allocated or generated):

```
$ helpmate gen KQRRvkqr --tables tt
error: not enough memory to generate slice KQRRvkqr: its four value planes
need ~1848.00 GiB but only 54.17 GiB is available (MemAvailable,
/proc/meminfo); re-run with --force-ram to override
```

`gen` builds **every** table needed to answer queries about MATERIAL — the
whole closure of sub-slices reachable via captures and promotions, in
topological order, before the root slice itself (the root's scan needs the
sub-slice tables to evaluate capture/promotion successors). Each slice writes
one `<name>.hm` table plus a `<name>.stats.json` sidecar into the tables
directory. **Existing files are left alone**, so re-running after adding a new
root material is cheap, and closures shared between materials are reused
automatically.

```
$ helpmate gen KQvk --tables tt
tt/Kvk.hm max_dtm=255
tt/KQvk.hm max_dtm=14
```

`Kvk` (king vs king — unconditionally unsolvable, hence `max_dtm=255`) is
built first because a Black king capturing the queen lands there; `KQvk`
itself tops out at `max_dtm=14`, i.e. the longest optimal helpmate in this
material is `h#7`. A re-run prints
`nothing to do: all tables for KQvk already exist in tt`.

## `probe` — look up one position

```
helpmate probe <FEN> [--tables DIR]
```

```
$ helpmate probe "8/7k/5K2/8/8/8/8/6Q1 b - - 0 1" --tables tt
dtm=2 (h#1) count=4
```

Output is `dtm=<plies> (<h#-notation>) count=<optimal lines>`. For a legal
but unsolvable position it prints `unsolvable` (still exit 0). If the
position's own slice is missing but the color-flipped slice exists, the probe
transparently flips colors and annotates the output
(`dtm=2 (h#1, colors flipped) count=4`).

## `line` — print optimal lines

```
helpmate line <FEN> [--tables DIR] [--all] [--max N]
```

- `--all`: print *every* optimal line, one per output line;
- `--max N`: cap on lines printed with `--all` (default 10).

```
$ helpmate line "8/7k/5K2/8/8/8/8/6Q1 b - - 0 1" --tables tt
Kh6 Qh2#

$ helpmate line "8/7k/5K2/8/8/8/8/6Q1 b - - 0 1" --tables tt --all
Kh6 Qh2#
Kh6 Qh1#
Kh6 Qg6#
Kh8 Qg7#
```

Moves are SAN. Lines are reconstructed by greedy descent through the dtm
planes (with the same en-passant adjustment applied during descent), so the
count of `--all` lines matches `probe`'s `count` (up to the `--max` cap). For
an unsolvable position — or one that is *already* checkmate, where there are
no moves to print — it prints
`unsolvable (or already mate: no line to print)` (exit 0). Note: unlike
`probe`, `line` has **no color-flip fallback** — it needs the position's own
slice generated, and exits 2 with the exact `helpmate gen` command otherwise.

## `stats` — generation statistics

```
helpmate stats <MATERIAL> [--tables DIR]
```

Prints the complete generation-time statistics JSON for one material class
(the same content as the `<name>.stats.json` sidecar written by `gen`):

```
$ helpmate stats KQvk --tables tt
{
  "material": "KQvk",
  "plane_size": 29568,
  "max_dtm": 14,
  "cells": { "invalid": {...}, "unsolvable": {...} },
  "dtm_histogram": { "wtm": {...}, "btm": {...} },
  "uniqueness": { "wtm": {...}, "btm": {...} },
  "deepest": [ "8/6k1/5Q2/8/8/8/8/K7 b - - 0 1", ... ],
  "deepest_unique": [ "8/8/7k/6Q1/8/8/8/K7 b - - 0 1", ... ],
  "generator_version": "0.1.0"
}
```

### `stats.json` field reference

Throughout, `wtm`/`btm` = White/Black to move; per-plane cell values are keyed
by side to move.

| Field | Meaning |
|---|---|
| `material` | canonical material name of the slice. |
| `plane_size` | number of index cells per plane (the symmetry-reduced position count per side to move; e.g. 29568 = 462 king-pair classes × 64 queen squares for `KQvk`). |
| `max_dtm` | deepest dtm in the slice, in plies; `255` if nothing in the slice is solvable (sentinel). |
| `cells.invalid.{wtm,btm}` | cells whose index decodes to no legal position for that side to move (e.g. side not to move in check, coincident squares). |
| `cells.unsolvable.{wtm,btm}` | legal positions from which no cooperative mate exists. |
| `dtm_histogram.{wtm,btm}` | object mapping dtm (as a string key) → number of positions with exactly that dtm. Depths with zero positions are omitted. |
| `uniqueness.{wtm,btm}` | object mapping dtm → (optimal-line count → number of positions): how many positions at each depth have exactly 1, 2, 3, … optimal solutions. Counts saturate at 255 ("255" = 255 or more). The `"1"` entries are the sound-composition candidates. |
| `deepest` | **a sample, capped at 5 FENs**, of positions at `max_dtm` (side to move follows dtm parity: odd = White to move, even = Black to move). |
| `deepest_unique` | **a sample, capped at 5 FENs**, of positions with a *unique* solution (`count = 1`) at the greatest depth where any such position exists (searching downward from `max_dtm`). |
| `generator_version` | version string of the generator that wrote the slice. |

**Important**: `deepest` and `deepest_unique` are illustrative *samples* (at
most 5 FENs each, taken in index order) — they are not exhaustive lists. The
complete, exact data lives in `dtm_histogram` and `uniqueness`; use `mine` to
enumerate the actual positions at any (dtm, count).

## `mine` — scan for composition candidates

```
helpmate mine <MATERIAL> --dtm D [--count C] [--max N] [--tables DIR]
```

- `--dtm D` (**required**): exact distance-to-mate, in plies, to match;
- `--count C` (optional): additionally require exactly C optimal solutions;
- `--max N`: cap on FENs printed (default 10).

Prints matching FENs one per line, scanning the slice's index planes (an O(1)
table read per cell — no search):

```
$ helpmate mine KQvk --dtm 2 --count 1 --max 3 --tables tt
8/8/8/8/8/8/8/k1KQ4 b - - 0 1
8/8/8/8/8/2Q5/8/k1K5 b - - 0 1
8/8/8/8/4Q3/8/8/k1K5 b - - 0 1
```

(three `h#1` positions with a *unique* solution — raw material for a sound
one-line composition; `--dtm 2 --count 2` would list positions with exactly
one dual, etc.)

## Exit codes

| Code | Meaning |
|---|---|
| `0` | success — including a reported `unsolvable` answer. |
| `2` | a table needed to answer the query is missing; the message names it and the exact `helpmate gen` command that builds it. |
| `3` | bad usage or unparseable input (unknown command, malformed FEN or material string, malformed/out-of-range numeric flag, flag missing its value). |

## Resource guidance

Per-slice plane sizes follow directly from the indexing scheme (four 1-byte
planes per slice: dtm and count for each side to move; a small header + JSON
metadata on top). `gen` always builds the whole capture/promotion closure, so
total time/space is the sum over all slices in the closure.

| Pieces | Typical generation time | Typical table size | Notes |
|---|---|---|---|
| 3 | well under a second (~0.6 s measured for the whole `KQvk` closure) | ~120 KB per pawnless slice (29,568 cells × 4 planes) | instant to experiment with |
| 4 | seconds | ~7.6 MB per pawnless slice (462 × 64² cells × 4 planes) | still interactive |
| 5 | minutes to a couple of hours, material-dependent | ~0.5 GB per pawnless slice (462 × 64³ ≈ 121 M cells × 4 planes) | see the known-bug note below |
| 6 | multi-day runs | roughly **14-28 GB** of table storage/RAM for a class at the current 1-byte/cell, uncompressed encoding | feasible but heavy; use `--threads` |
| 7-8 | out of scope for this version | — | the versioned format is designed so a future compressed/out-of-core encoding can be added without invalidating existing tables |

Pawnful slices index 1806 king-pair classes (×48 per pawn instead of ×64), so
they are larger per remaining piece than the pawnless numbers above. Tables
are mmap-backed: probing costs a page fault, not a full load, so querying huge
tables is cheap even when generation was not.

**Known issue**: 5-piece generation has had a known, intermittent crash bug
(heap corruption in the root-slice generation scan — bug #21); see the
Limits and Coverage sections of the [README](../README.md) for its current
status. Re-running `gen` is safe: completed slices are never rewritten, so a
crashed run resumes where it left off.

## Python API

Install per [BUILD.md](BUILD.md) (`pip install .`), then:

```python
import helpmate

# build (or reuse, if already built) every table this material class needs;
# returns the list of table files actually written
helpmate.generate("KQvk", tables="tables/", threads=4)

tb = helpmate.Tablebase("tables/")

dtm, count, flipped = tb.probe("8/7k/5K2/8/8/8/8/6Q1 b - - 0 1")
# dtm=2, count=4, flipped=False

tb.line("8/7k/5K2/8/8/8/8/6Q1 b - - 0 1")
# ['Kh6', 'Qh2#']

tb.lines("8/7k/5K2/8/8/8/8/6Q1 b - - 0 1", max=10)
# [['Kh6', 'Qh2#'], ['Kh6', 'Qh1#'], ['Kh6', 'Qg6#'], ['Kh8', 'Qg7#']]

tb.mine("KQvk", dtm=2, count=1, max=3)
# ['8/8/8/8/8/8/8/k1KQ4 b - - 0 1', '8/8/8/8/8/2Q5/8/k1K5 b - - 0 1', ...]

tb.stats("KQvk")["max_dtm"]
# 14
```

Reference:

- `helpmate.generate(material, tables="tables", threads=1, verbose=False,
  progress=False, force_ram=False)` — generates the closure exactly like the
  CLI's `gen` (the three keyword flags match `--verbose`, `--progress`,
  `--force-ram`; reporting goes to the process's stderr); returns the list of
  `.hm` paths written (empty if everything already existed).
- `Tablebase(tables_dir)` — lazily mmap-loads and caches whatever slices
  queries touch.
- `tb.probe(fen)` — returns a `(dtm, count, flipped)` tuple, or **`None`** for
  a legal but unsolvable position. `flipped=True` means the answer came from
  the color-flipped slice.
- `tb.line(fen)` — one optimal line as a list of SAN strings (empty list if
  unsolvable or already mate).
- `tb.lines(fen, max=100)` — every optimal line, capped at `max`.
- `tb.mine(material, dtm, count=-1, max=100)` — list of FENs matching `dtm`
  exactly and, if `count >= 0`, `count` exactly.
- `tb.stats(material)` — the stats JSON as a Python dict (fields as in the
  [reference](#statsjson-field-reference) above).

Errors: a missing table with no usable color-flip fallback raises
`helpmate.MissingTableError` (a `RuntimeError` subclass) whose message names
the exact `helpmate gen` invocation that would build it; malformed FENs or
material strings raise `ValueError`.

Python tests live in `tests/python/` (`pytest tests/python`; add `--run-slow`
for the exhaustive python-chess cross-validation of the full KQvk closure).
