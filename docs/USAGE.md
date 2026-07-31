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
`helpmate --help` prints the full usage text, every flag, and the exit codes;
`helpmate --version` prints the version (e.g. `helpmate 0.5.0`).

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
  "generator_version": "0.5.0"
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
helpmate mine <MATERIAL> --dtm D [--count C] [--starts N] [--ends N] [--max N] [--tables DIR]
```

- `--dtm D` (**required**): exact distance-to-mate, in plies, to match;
- `--count C` (optional): additionally require exactly C optimal solutions;
- `--starts N` (optional): additionally require exactly N *distinct first
  moves* across the optimal solutions — i.e. how many different ways White
  can begin the mate, ignoring how each one finishes;
- `--ends N` (optional): additionally require exactly N *distinct mating
  moves* across the optimal solutions — i.e. how many different final moves
  deliver mate, ignoring how each one got there;
- `--max N`: cap on FENs printed (default 10).

`--starts`/`--ends` are exact-match filters, evaluated (cheaply) only for
positions that already matched `--dtm`/`--count` — a position that matches
`--dtm 2 --count 4` but has 3 distinct first moves is excluded by `--starts
2` just as surely as one with the wrong `--dtm`. Both must be `>= 1`, and if
`--count` is also given, each must be `<= --count` (a position with C
solutions cannot have more than C distinct starts or ends); violating either
rule is a usage error (exit 3), not a silently empty result — including a
literal `-1`, which is otherwise a value `--starts`/`--ends` could take.

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

`--starts`/`--ends` narrow this further to a specific *shape* of dual: take
`8/8/8/8/8/2K5/7Q/1k6 b - - 0 1` (`dtm=2, count=4`), whose four optimal
lines are `Ka1 Qb2#`, `Kc1 Qg1#`, `Kc1 Qh1#`, `Kc1 Qc2#`. Only two distinct
first moves appear (`Ka1`, `Kc1` — one of them, `Kc1`, has three tries), but
all four mating moves are distinct, so this position has `starts=2, ends=4`:

```
$ helpmate mine KQvk --dtm 2 --count 4 --starts 2 --ends 4 --max 3 --tables tt
8/8/8/8/8/2K5/4Q3/1k6 b - - 0 1
8/8/8/8/8/2K5/7Q/1k6 b - - 0 1
```

(the second FEN printed is the position above, in its canonical — i.e.
symmetry-reduced — form; `mine` always prints canonical FENs, which need not
match the FEN a query used to reach the same position.)

If any matched position's solution count is *saturated* (stored as 255+,
meaning the true count is unenumerable — see [DTM
semantics](#dtm-semantics-plies-hn-notation)), it can't be checked against
`--starts`/`--ends` and is skipped rather than guessed at; `mine` tallies
these and, if any were skipped, prints a note to stderr when it exits:

```
note: skipped N position(s) whose solution count is saturated (255+): their
solutions cannot be enumerated exhaustively
```

(`KQvk` has no saturated-count positions, so this note never fires for the
examples above; it applies to richer material classes where hundreds of
optimal replies can tie.)

## `compact` — reclaim disk space in already-unsolvable tables

```
helpmate compact <DIR> [--dry-run]
```

Rewrites every `.hm` table in `DIR` whose cells are **all** unsolvable (or
invalid) into a tiny marker file, reclaiming disk space without changing what
any query can answer. Tables with at least one solvable cell are left
completely untouched, and a table that is already a marker is skipped (not
rewritten again). When a run rewrites nothing at all — every table was either
solvable or already a marker — it prints `already compact`. `--dry-run`
reports what *would* be rewritten and reclaims nothing — it never opens a
file for writing.

This exists for tables generated **before v0.6.1**, when `gen` had no pruning
and wrote a full-size table even for slices like `Kvk` where every cell is
unsolvable. Since v0.6.1, `gen` already prunes such slices to markers at
generation time (see [Pruning and marker tables](#pruning-and-marker-tables)
below) — so `compact` typically has nothing to do on tables generated after
the upgrade; run it once against older tables to shrink them in place.

Real captured output below. `demo/` holds a real, freshly generated `KQvk`
closure (`KQvk.hm` — solvable, left alone) next to a fabricated stand-in for
a pre-v0.6.1 `Kvk.hm`: a full-size, ordinary (version 1) table whose every
cell is unsolvable, the shape `compact` exists to shrink.

```
$ ls -l demo/
-rw-r--r-- 1 os users 146117 KQvk.hm
-rw-r--r-- 1 os users  27781 KQvk.stats.json
-rw-r--r-- 1 os users   4087 Kvk.hm

$ helpmate compact demo --dry-run
would rewrite Kvk (0 MiB)
would reclaim 0 MiB from 1 table(s); 1 left unchanged (solvable or already compact)

$ ls -l demo/          # --dry-run wrote nothing; every size unchanged
-rw-r--r-- 1 os users 146117 KQvk.hm
-rw-r--r-- 1 os users  27781 KQvk.stats.json
-rw-r--r-- 1 os users   4087 Kvk.hm

$ helpmate compact demo
rewrote Kvk (0 MiB)
reclaimed 0 MiB from 1 table(s); 1 left unchanged (solvable or already compact)

$ ls -l demo/          # Kvk.hm shrank; KQvk.hm/.stats.json byte-identical
-rw-r--r-- 1 os users 146117 KQvk.hm
-rw-r--r-- 1 os users  27781 KQvk.stats.json
-rw-r--r-- 1 os users    469 Kvk.hm
-rw-r--r-- 1 os users    405 Kvk.stats.json

$ helpmate compact demo    # re-run: nothing left to do
reclaimed 0 MiB from 0 table(s); 2 left unchanged (solvable or already compact)
already compact

$ helpmate probe "8/7k/5K2/8/8/8/8/6Q1 b - - 0 1" --tables demo
dtm=2 (h#1) count=4
```

(`Kvk`'s 4087→469 bytes is a rounding-to-0-MiB demo at 2-piece scale; the same
mechanism reclaims gigabytes on a real 5-6 piece run where a dead slice would
otherwise have been a multi-GB full table.) The rewritten `.stats.json`
sidecar is regenerated fresh, not copied from the original — it carries
`"all_unsolvable": true` and the compacting binary's own
`generator_version`, exactly like a marker `gen` produces directly.

### Pruning and marker tables

Since v0.6.1, `gen` skips writing a full table for any slice it can *prove*
contains no helpmate at all, writing a **marker table** instead. A slice is
pruned when either:

- **the mating side is a bare king** — White (the side the index always
  treats as delivering mate; see [Symmetry reduction](#symmetry-reduction))
  has no piece besides its king. A lone king can never deliver check, so the
  slice is unsolvable regardless of what Black holds (e.g. `Kvk`, `Kvkq`,
  `Kvkr` are all pruned this way, unconditionally); or
- **every successor's table reports all of its cells unsolvable, and the
  slice has no checkmate position of its own** — every solution ends in a mate
  either in this slice or in one reached by a capture/promotion, so if every
  reachable successor slice is proven dead *and* scanning this slice directly
  finds no checkmate, the slice is dead too.

A **marker table** is a table file with no payload at all: just the 64-byte
header (format `version = 2`, versus `1` for an ordinary table) plus the
metadata JSON — the four value planes (dtm/count × White-to-move/Black-to-move)
that make up the bulk of an ordinary table's bytes are simply not written.
Every cell reads back as `DTM_UNSOLVABLE` when probed, exactly as it would if
the slice had been generated in full and turned out to be entirely
unsolvable. `TableReader` accepts both versions transparently — probing,
`stats`, `mine`, and `compact` all work unchanged whether a table on disk is
an ordinary version-1 table or a version-2 marker; nothing reading tables
needs to change for this feature.

Since v0.6.2, a table file whose format `version` is newer than this build
understands is diagnosed as such — `error: table ... was written by a newer
helpmate (unsupported table format version); upgrade this build` (exit code
`3`) — rather than being reported as a missing table (exit code `2`); the
message is what tells "you need to build it" apart from "you need a newer
helpmate". This applies wherever a table is read: `compact` reports it and
exits 3, and `gen --prune`'s successor-table check treats it as an error
rather than silently assuming the successor isn't proven dead. `probe` is the
one place it isn't necessarily fatal: a future-format table only stops the
query if it *also* defeats the color-flip fallback above — if the position's
own slice is the one that's unreadable but the color-flipped slice is a
usable, understood table, `probe` answers from the flip exactly as it would
for a missing (not just future-format) primary slice, and the version
mismatch is never reported at all.

## Exit codes

| Code | Meaning |
|---|---|
| `0` | success — including a reported `unsolvable` answer. |
| `2` | a table needed to answer the query is missing; the message names it and the exact `helpmate gen` command that builds it. |
| `3` | bad usage or unparseable input (unknown command, malformed FEN or material string, malformed/out-of-range numeric flag, flag missing its value; includes `compact` given no directory, or a path that is not a directory) — also a table written by a newer helpmate (unsupported table format version), which is a runtime error rather than bad usage but shares this exit code. |

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
- `tb.mine(material, dtm, count=-1, max=100, starts=-1, ends=-1)` — list of
  FENs matching `dtm` exactly and, for each of `count`/`starts`/`ends` that
  is `>= 0`/`>= 1`, that criterion exactly too (`starts`/`ends`: distinct
  first moves / distinct mating moves among the optimal solutions — see the
  CLI [`mine`](#mine--scan-for-composition-candidates) section for what
  these mean).
- `tb.mine_with_stats(material, dtm, count=-1, max=100, starts=-1, ends=-1)`
  — like `tb.mine`, but returns `(fens, skipped_saturated)`: the FEN list
  plus how many matched-so-far positions were skipped because their stored
  solution count is saturated (255+) and so couldn't be checked against
  `starts`/`ends`.
- `tb.stats(material)` — the stats JSON as a Python dict (fields as in the
  [reference](#statsjson-field-reference) above).

Errors: a missing table with no usable color-flip fallback raises
`helpmate.MissingTableError` (a `RuntimeError` subclass) whose message names
the exact `helpmate gen` invocation that would build it; malformed FENs or
material strings raise `ValueError`.

Python tests live in `tests/python/` (`pytest tests/python`; add `--run-slow`
for the exhaustive python-chess cross-validation of the full KQvk closure).

## API server

A small read-only HTTP API (FastAPI + uvicorn) for serving generated tables:
health/catalog/stats, `probe`/`line`/`mine` as JSON, and transparent
on-demand fetching of tables that only live in a remote Hugging Face
dataset. Plus a companion CLI, `helpmate-tables`, for pushing tables to and
pulling them from that dataset.

### Install

```bash
pip install ".[server]"
```

This installs `fastapi`, `uvicorn`, and `huggingface_hub` on top of the base
package, and registers two console scripts: `helpmate-server` and
`helpmate-tables`.

### Start the server

```bash
helpmate-server --tables ~/myhelpmate/tables --hf-repo USER/DS \
  --cache ~/.cache/helpmate-tables --port 8642
```

- `--tables DIR` (repeatable): one or more local directories searched, in
  order, for `.hm`/`.stats.json` files. Omit entirely to serve only from the
  remote.
- `--hf-repo USER/DATASET` + `--cache DIR`: an optional Hugging Face dataset
  repo consulted when a material isn't found in any `--tables` dir; downloads
  land in `--cache` (`--hf-repo` requires `--cache`, and vice versa isn't
  enforced but is pointless).
- `--host` / `--port`: default `127.0.0.1:8642`.
- `--mine-cap` (default `1000`) / `--mine-timeout` (default `30.0` seconds):
  see [`/v1/mine`](#get-v1mine) below.

All examples below were captured from a real, locally running server
(`helpmate-server --tables <scratch>` with `<scratch>` generated via
`helpmate.generate("KQvk", tables="<scratch>", threads=2)`, i.e. the `KQvk`
closure: `KQvk` + `Kvk`), on `127.0.0.1:8642`.

### Error envelope

Every non-2xx, non-202 response (including framework-generated 404/405s and
uncaught exceptions) has the same shape:

```json
{"error": {"code": "unknown_material", "message": "...", "hint": "..."}}
```

`hint` is `null` when there is nothing actionable to add.

### `GET /v1/health`

```
$ curl -s http://127.0.0.1:8642/v1/health
{"status":"ok","version":"0.6.0.dev0","tables_local":2,"tables_remote":0}
```

### `GET /v1/materials`

Lists every material the chain of local dirs + remote manifest knows about
(one entry per resolved `.hm`/catalog file; `location` is `local`, `cached`,
or `remote`).

```
$ curl -s http://127.0.0.1:8642/v1/materials
{"materials":[{"material":"KQvk","pieces":3,"size_bytes":146117,"max_dtm":14,"cells":29568,"location":"local"},{"material":"Kvk","pieces":2,"size_bytes":2288,"max_dtm":255,"cells":462,"location":"local"}]}
```

`max_dtm`/`cells` are `null` for a `remote` entry (not yet downloaded, so the
stats sidecar hasn't been read).

### `GET /v1/materials/{name}/stats`

The full `stats.json` for one material class (same content as `helpmate
stats`; see the [field reference](#statsjson-field-reference) above).

```
$ curl -s http://127.0.0.1:8642/v1/materials/KQvk/stats
{"material":"KQvk","plane_size":29568,"max_dtm":14,"cells":{"invalid":{"wtm":11487,"btm":1512},"unsolvable":{"wtm":0,"btm":414}},"dtm_histogram":{...},"uniqueness":{...},"deepest":[...],"generator_version":"0.5.0"}
```

Unknown material → 404 with the standard envelope:

```
$ curl -s http://127.0.0.1:8642/v1/materials/KNvkqr/stats
{"error":{"code":"unknown_material","message":"no table for material 'KNvkqr'","hint":"generate it with: helpmate gen KNvkqr --tables <dir>"}}
```

### `GET /v1/probe`

```
$ curl -sG http://127.0.0.1:8642/v1/probe --data-urlencode "fen=8/7k/5K2/8/8/8/8/6Q1 b - - 0 1"
{"dtm":2,"count":4,"flipped":false,"notation":"h#1"}
```

A legal but unsolvable position reports `{"solvable": false}` (no `dtm`
field):

```
$ curl -sG http://127.0.0.1:8642/v1/probe --data-urlencode "fen=8/8/8/8/8/4k3/8/4K3 w - - 0 1"
{"solvable":false}
```

A malformed FEN is a 400, not a 404:

```
$ curl -sG http://127.0.0.1:8642/v1/probe --data-urlencode "fen=garbage"
{"error":{"code":"invalid_fen","message":"substring not found","hint":null}}
```

Like the CLI, `probe` transparently falls back to the color-flipped material
when only that slice is generated, and reports it via `"flipped": true`.

### `GET /v1/line`

`?all=true` returns every optimal line instead of just the first.

```
$ curl -sG http://127.0.0.1:8642/v1/line --data-urlencode "fen=8/7k/5K2/8/8/8/8/6Q1 b - - 0 1"
{"lines":[["Kh6","Qh2#"]]}

$ curl -sG http://127.0.0.1:8642/v1/line --data-urlencode "fen=8/7k/5K2/8/8/8/8/6Q1 b - - 0 1" --data-urlencode "all=true"
{"lines":[["Kh6","Qh2#"],["Kh6","Qh1#"],["Kh6","Qg6#"],["Kh8","Qg7#"]]}
```

### `GET /v1/mine`

Parameters: `material`, `dtm` (required), `count` (optional, exact match),
`starts` / `ends` (optional, exact match on the number of distinct first
moves / distinct mating moves among the optimal solutions — see the CLI
[`mine`](#mine--scan-for-composition-candidates) section for what these mean
and why the golden `8/8/8/8/8/2K5/7Q/1k6 b - - 0 1` position has `starts=2,
ends=4`), and `max`.

```
$ curl -sG http://127.0.0.1:8642/v1/mine --data-urlencode "material=KQvk" --data-urlencode "dtm=2" --data-urlencode "count=1" --data-urlencode "max=3"
{"fens":["8/8/8/8/8/8/8/k1KQ4 b - - 0 1","8/8/8/8/8/2Q5/8/k1K5 b - - 0 1","8/8/8/8/4Q3/8/8/k1K5 b - - 0 1"],"truncated":true,"skipped_saturated":0}
```

Every response carries `skipped_saturated`: the number of matched-so-far
positions whose stored solution count was saturated (255+, unenumerable) and
so had to be skipped rather than checked against `starts`/`ends` — 0 when no
`starts`/`ends` filter is given, or when nothing saturated was encountered
(as above; `KQvk` has no saturated-count positions). `starts`/`ends` narrow
the match to a specific dual shape:

```
$ curl -sG http://127.0.0.1:8642/v1/mine --data-urlencode "material=KQvk" --data-urlencode "dtm=2" --data-urlencode "count=4" --data-urlencode "starts=2" --data-urlencode "ends=4" --data-urlencode "max=3"
{"fens":["8/8/8/8/8/2K5/4Q3/1k6 b - - 0 1","8/8/8/8/8/2K5/7Q/1k6 b - - 0 1"],"truncated":false,"skipped_saturated":0}
```

`starts`/`ends` must each be `>= 1`, and `<= count` if `count` is also given
(a position with `count` solutions can't have more distinct starts or ends
than that); violating either is a `400 invalid_filter`, e.g. asking for more
starts than the position could possibly have:

```
$ curl -sG http://127.0.0.1:8642/v1/mine --data-urlencode "material=KQvk" --data-urlencode "dtm=2" --data-urlencode "count=4" --data-urlencode "starts=5"
{"error":{"code":"invalid_filter","message":"starts=5 cannot exceed count=4","hint":"a position with N solutions has at most N distinct starting or mating moves"}}
```

`truncated` is `true` whenever more matches exist than were returned (as
here: `KQvk` has more than 3 positions at `dtm=2, count=1`, so `max=3` cuts
it off) — either because the caller's own `?max=` was reached, or because
the server-side `--mine-cap` was reached first (whichever is smaller wins;
the request's `max` is clamped to `min(max, mine-cap)`). Example with a
server started as `helpmate-server --tables <scratch> --mine-cap 3` and the
client asking for
`max=50` (more than 3 matches exist at this dtm, so the 3-row server cap
bites, not the client's 50):

```
$ curl -sG http://127.0.0.1:8644/v1/mine --data-urlencode "material=KQvk" --data-urlencode "dtm=2" --data-urlencode "max=50"
{"fens":["8/8/8/8/8/8/8/k1KQ4 b - - 0 1","8/8/8/8/8/2Q5/8/k1K5 b - - 0 1","8/8/8/8/1Q6/8/8/k1K5 b - - 0 1"],"truncated":true,"skipped_saturated":0}
```

If the scan doesn't finish within `--mine-timeout` seconds (default 30; a
server-only setting, not a query parameter), the endpoint returns an empty,
truncated result rather than blocking indefinitely, with a `note` field
explaining why (server started as `helpmate-server --tables <scratch>
--mine-timeout 0`, forcing an immediate timeout):

```
$ curl -sG http://127.0.0.1:8645/v1/mine --data-urlencode "material=KQvk" --data-urlencode "dtm=2"
{"fens":[],"truncated":true,"note":"timeout","skipped_saturated":0}
```

When a scan genuinely exhausts the whole material with fewer matches than
`max`/`mine-cap`, `truncated` is `false` (e.g. `Kvk` is unsolvable
everywhere, so `dtm=2` matches nothing):

```
$ curl -sG http://127.0.0.1:8642/v1/mine --data-urlencode "material=Kvk" --data-urlencode "dtm=2"
{"fens":[],"truncated":false,"skipped_saturated":0}
```

### The 202-fetching contract

Any endpoint that needs a material (`stats`, `probe`, `line`, `mine`) checks
the local `--tables` dirs first, then the `--hf-repo` remote if configured.
If the material is only in the remote manifest and not yet cached locally,
the **first** request that touches it kicks off a background download and
immediately returns `202 Accepted`. (The examples below use port 8643 — a
second real server, started with `KQvk` only in a fake remote-hub manifest
and no local `--tables` copy, to exercise this path; `--hf-repo` in practice
points at a real Hugging Face dataset instead of a fake hub.)

```
$ curl -si http://127.0.0.1:8643/v1/materials/KQvk/stats
HTTP/1.1 202 Accepted
content-type: application/json

{"status":"fetching","material":"KQvk","size_bytes":146117}
```

Any request that arrives **while** the download is still in flight (whether
it's the same client polling or a different one) also gets `202`, this time
without `size_bytes` (already known to be fetching, no need to look it up
again):

```
$ curl -si http://127.0.0.1:8643/v1/materials/KQvk/stats
HTTP/1.1 202 Accepted
content-type: application/json

{"status":"fetching","material":"KQvk"}
```

Once the download finishes (verified against the manifest's sha256; see
below), subsequent requests resolve normally with `200`:

```
$ curl -si http://127.0.0.1:8643/v1/materials/KQvk/stats
HTTP/1.1 200 OK
content-type: application/json

{"material":"KQvk","plane_size":29568,...}
```

If the download fails (network error, sha256 mismatch), the state becomes
`failed` and requests get a `502` with `fetch_failed`:

```json
{"error": {"code": "fetch_failed", "message": "download of 'KQvk' failed",
           "hint": "check server logs; retry triggers a new download"}}
```

The `hint` is truthful: the very request that *observes* the `failed` state
(the one returning this `502`) re-triggers `start_fetch` before responding,
so by the time the client retries, the download is already under way again.
Concretely: request N discovers the failure and answers `502`; request N+1
already sees `fetching` and answers `202`; once the retried download
finishes, subsequent requests resolve `200` as normal. No server restart
is needed to recover from a bad download.

A material present in neither local dirs nor the remote manifest is a plain
`404 unknown_material`, same as the fully-offline case.

### `helpmate-tables` — push/pull to a Hugging Face dataset

```bash
pip install ".[server]"   # same extra as the API server
```

```
helpmate-tables push --tables DIR --repo USER/DATASET [--material NAME ...]
helpmate-tables pull --tables DIR --repo USER/DATASET [--material NAME ...]
```

- `--tables DIR`: local directory to push from / pull into.
- `--repo USER/DATASET`: a Hugging Face **dataset** repo id.
- `--material NAME` (repeatable): restrict the operation to specific
  materials (matches both the `.hm` and `.stats.json` files for that name).
  **Omit it to operate on every material** — `push` with no `--material`
  uploads every `.hm`/`.stats.json` pair found under `--tables`; `pull` with
  no `--material` downloads every material listed in the remote manifest.

**`push`** first (re)writes a local `manifest.json` in `--tables` covering
*every* file currently in that directory (not just the ones being pushed),
then fetches the *existing remote* manifest (if any) and **merges**: files
for the pushed materials are added/updated with their fresh sha256/size,
while every other entry already on the remote manifest is carried forward
unchanged. This means a scoped `push --material X` never forgets materials
a previous, different push already uploaded — the remote manifest only ever
grows or updates, never shrinks, from a scoped push. If the remote has no
manifest yet (first push to a fresh dataset repo), the merge starts from an
empty file set.

**`pull`** fetches the remote manifest, downloads the requested (or, by
default, *all*) `.hm`/`.stats.json` files into `--tables`, and verifies each
downloaded file's sha256 against the manifest entry before accepting it;
a mismatch deletes the partial file and fails the whole pull.

### Manifest format (`manifest.json`)

```json
{
  "schema": 1,
  "generator_version": "0.5.0",
  "files": {
    "KQvk.hm": {"sha256": "<hex>", "size": 146117},
    "KQvk.stats.json": {"sha256": "<hex>", "size": 27781}
  }
}
```

`generator_version` is read from the first `*.stats.json` found in
`--tables` (`"unknown"` if none exist yet). `files` maps every `.hm`/
`.stats.json` filename present under `--tables` at push time to its sha256
and byte size — these are the only two file patterns the manifest ever
records. When `pull` has no `--material`, it derives "all materials" from
every `.hm` entry in `files` (its `.stats.json` sibling is pulled too, if
present).

### Exit codes (`helpmate-tables`)

| Code | Meaning |
|---|---|
| `0` | success. |
| `1` | operation failed after starting (network error, remote has no manifest on `pull`, sha256 mismatch, upload error) — message on stderr, no traceback. |
| `2` | bad usage (`--tables` not a directory, no subcommand given). |

### Smoke-testing a running server

`tools/api_smoke.py` exercises every `/v1` route against a live server and
checks response shapes, the error envelope, and — when a `KQvk` table is
served — the golden values pinned by the C++/Python/CLI test suites. It uses
only the Python standard library, so it runs anywhere the server does,
including against a remote deployment.

```console
$ helpmate-server --tables ~/tb --port 8642 &
$ python3 tools/api_smoke.py --url http://127.0.0.1:8642
helpmate API smoke test against http://127.0.0.1:8642

[health]
  ok   GET /v1/health -> 200
  ok   health reports status/version
       version 0.6.0, 2 local / 0 remote table(s)

[catalog]
  ok   GET /v1/materials -> 200
  ok   catalog is non-empty
  ok   catalog entries carry pieces/size/location
       KQvk, Kvk
       exercising material: KQvk
...
[errors]
  ok   invalid FEN -> 400 envelope
  ok   missing parameter -> 400 envelope
  ok   path traversal in material -> 400 envelope
  ok   unknown material -> 404 envelope with a gen hint
  ok   unknown route -> 404 envelope

20 passed, 0 failed
```

Options:

| Flag | Meaning |
|---|---|
| `--url URL` | base URL of the running server (default `http://127.0.0.1:8642`). |
| `--material NAME` | material to exercise `probe`/`line`/`mine` against. Defaults to `KQvk` when it is served (enabling the golden-value checks), otherwise the first catalogued material — for which the script mines a position and verifies that `probe` and `line` agree with it. |
| `--fetch-timeout N` | when a route answers `202 fetching` (the material lives only on the remote), keep polling for up to `N` seconds instead of skipping the check. Downloads can be large; `0` (the default) does not wait. |

Exit status: `0` all checks passed, `1` at least one failed (each is listed
again at the end), `2` the server was unreachable.
