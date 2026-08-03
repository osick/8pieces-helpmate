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

### Table format

Every `.hm` file opens with the same 64-byte header (magic, `version`,
`encoding`, canonical material name, symmetry kind, plane size, max dtm) plus
a length-prefixed JSON metadata blob; what follows the header depends on
`version`:

- **version 1** — an ordinary table: four contiguous byte planes (DTM-white,
  DTM-black, count-white, count-black), one byte per index cell, `encoding =
  1` (raw).
- **version 2** — a **marker** table: header + JSON only, no payload at all.
  Every cell reads as unsolvable/invalid. Written when a slice's closure
  computation finds no solvable cell at all (e.g. `Kvk`); see
  [Pruning and marker tables](#pruning-and-marker-tables) below.
- **version 3** — a **block-compressed** table (since v0.7.5), `encoding =
  2`. The four planes are treated as one logical byte range, cut into
  fixed-size blocks (**64 KiB by default**, tunable via `--block-size`; see
  below), each compressed independently with zstd (level 3 by default), plus
  a `uint64` offset index and a small bounded cache of decompressed blocks in
  the reader (sized off `block_size`, ~4 MB total regardless of the size
  chosen). Random access is preserved — a probe decompresses at most one
  block, not the whole table.

  **If you actively mine a table, know this before you compress it.**
  `helpmate mine --count`/`--starts` — which computes each matching
  position's full optimal-solution count, not just whether it is solvable —
  runs **~6.5x slower** on a compressed table than on the raw equivalent
  (measured on a real 462 MiB `KRvkbn` table, see the numbers below), and
  this holds at *every* block size measured, 16 KiB through 64 KiB. That
  path evaluates every legal move from a position to count optimal replies,
  and most quiet moves stay within the *same* material's table at cell
  indices that have no relationship to move adjacency — so the access
  pattern is effectively random across the whole table, and nearly every
  probe misses the reader's small decompressed-block cache and pays a full
  block decompression to read one byte. A plain sequential scan (`mine`
  without `--count`/`--starts`) barely notices (**+14%**), and a single
  `probe` barely notices either (**+9%**) — the cost is specific to the
  random-access `--count`/`--starts` path. A single warm probe measured 2.94
  us -> 3.02 us (1.09x), and the raw `get()` path itself costs 18.3 ns ->
  19.3 ns (+5.5%) simply from one reader having to support both formats. If
  your workload is `mine --count`/`--starts` over a compressed corpus,
  budget for ~6.5x there specifically; everything else is single-digit
  percent.

  Compression ratio depends heavily on table size and block size: a real
  6-piece plane measured 14.5x at 64 KiB/level 3, and a real 5-piece table
  (`KBvkbn`) went from 462 MiB to 50 MiB end to end (9.22x) at 64 KiB. Small
  materials compress far less well — `KQvk` at 146 KB measures only 2.0x at
  64 KiB — because the fixed per-file overhead (header, JSON, a block index
  covering just 2-3 blocks) dominates a file too small to give zstd much to
  work with. This is expected, not a defect: don't read "only 2x" on a toy
  table as evidence something is broken.

  **Why the default is 64 KiB, not something smaller — a hypothesis that
  was tried and rejected.** Smaller blocks are cheaper to decompress per
  cache miss, so a 16 KiB default was tried on the theory that it would cut
  the `mine --count`/`--starts` regression above. In isolation the
  per-block-miss numbers looked promising: 16 KiB/level 3 gives an 11.4x
  ratio at ~11 us per block miss; 64 KiB/level 3 gives 14.5x at ~38 us —
  smaller blocks trade ratio for per-miss cost, so 16 KiB became the
  default for one version.

  **Measured end to end against a real table, the theory did not pan out,
  and 16 KiB was reverted before release rather than kept on the strength of
  the isolated numbers.** Reproducing the `mine --count` regression on a
  real `KRvkbn` table (462 MiB raw; closure `KRvkbn` + `KRvkb` + `KRvkn` +
  `KRvk` + `Kvk`; `helpmate mine KRvkbn --dtm 8 --count 1 --max 20000`,
  `/usr/bin/time`, two runs each):

  | table            | size (bytes)  | size    | ratio | elapsed (2 runs) | vs raw |
  |------------------|---------------|---------|-------|-------------------|--------|
  | raw               | 484,493,974  | 462.0 MiB | 1x   | 0.05s, 0.05s     | 1x     |
  | compressed, 64 KiB | 74,243,651  | 70.8 MiB  | 6.53x | 0.32s, 0.33s     | ~6.5x  |
  | compressed, 16 KiB | 81,545,441  | 77.8 MiB  | 5.94x | 0.32s, 0.33s     | ~6.5x  |

  The 16 KiB run was produced by *re-blocking* the 64 KiB table in place
  (`compact --compress --block-size 16`, see below) rather than regenerating
  it, and its bytes were confirmed identical to compressing the same raw
  table directly at 16 KiB (`md5sum` match, all four non-marker files in the
  closure). **16 KiB brought no measurable speed improvement over 64 KiB in
  this reproduction** — both ran the mining workload in ~0.32-0.33s, roughly
  6.5x the raw baseline, not the ~1.5-2x the isolated per-block-miss numbers
  predicted — **while compressing 8% worse** (77.8 MiB vs. 70.8 MiB, 5.94x
  vs. 6.53x). That is a pure loss: less compression and no measured speed
  benefit. (The original real-world report that motivated trying a smaller
  block measured 5x at 64 KiB on a slightly different 477 MB table; 6.5x
  here is the same class of regression, on different hardware/table.)

  So the default was moved back to 64 KiB. A plausible explanation for why
  decompression cost doesn't drive the regression, not yet confirmed by
  profiling: `BlockCache`'s miss path (`src/core/format/block_cache.cpp`)
  heap-allocates a fresh buffer and takes a mutex for every miss regardless
  of block size, and that fixed per-miss bookkeeping cost may dominate over
  the shrinking pure-decompress time, masking the benefit the isolated
  block-level numbers predict. Treat that as an open, unconfirmed
  hypothesis — the next step is profiling `BlockCache`'s miss path, not
  guessing at another block size. Re-run `tools/bench_compression.py` (or
  the `mine --count` reproduction above) against your own tables if this
  matters for your workload.

**Older binaries and compressed tables.** A version-3 table is readable only
by v0.7.5+. A pre-0.7.5 binary that encounters one does not report a generic
"unreadable table" error — the version field is checked before the payload
is touched, so it reports *"table ... was written by a newer helpmate
(unsupported table format version); upgrade this build"*, same message a
future version-4+ format would produce. `gen` and `probe` both surface this
distinction (`OpenError::UnsupportedVersion` vs. `Unreadable`).

**Opting in.** `helpmate gen --compress` writes new tables directly as
version 3 instead of version 1; raw stays the default (`gen` without the
flag behaves exactly as before) — the default flips to compressed in a
later version, once the performance gate above has been re-run at larger
scale than a handful of measured materials. `helpmate compact --compress`
instead rewrites *existing* raw tables on disk to block-compressed, one file
at a time via a temp file and atomic rename, streaming off the source
table's mmap at constant memory rather than buffering all four planes (a
6-piece table's four planes are ~31 GB; the converter's own peak RSS is
12-14 MiB regardless of table size). It leaves markers and tables that are
already compressed alone, and — like plain `compact` — skips any `.hm` file
whose material doesn't match its filename. It also skips any file **written
in the last hour**, checked before the file is even opened: a multi-hour/
multi-day generation run may still be writing into the same directory, and
rewriting a table mid-write would corrupt it, so `compact --compress` simply
leaves recent files for a later run rather than risking that.

See `tools/bench_compression.py` (documented in [BUILD.md](BUILD.md)) to
re-measure any of the numbers above against your own hardware or a larger
table.

## Getting the binary

Build per [BUILD.md](BUILD.md); the CLI lands at `./build/helpmate`. Running
`helpmate --help` prints the full usage text, every flag, and the exit codes;
`helpmate --version` prints the version (e.g. `helpmate 0.5.0`).

Common options (all subcommands): `--tables DIR` — the table directory
(default `tables`).

## `gen` — generate tables

```
helpmate gen <MATERIAL> [--tables DIR] [--threads N] [--verbose] [--progress] [--force-ram] [--compress] [--block-size N]
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
- `--compress`: write every table in this run as block-compressed (version
  3) instead of raw (version 1). Raw remains the default when the flag is
  omitted. **If you plan to `mine --count`/`--starts` against these tables,
  know that path runs ~6.5x slower on a compressed table than raw, at any
  block size** (plain scans +14%, single probes +9% — see [Table
  format](#table-format) above for the full measured numbers and why),
  before deciding whether to compress this corpus.
- `--block-size N`: only meaningful with `--compress`. Block size **in
  KiB** — `--block-size 64` means 64 KiB (65536 bytes), matching how the
  size/miss-cost trade-off is discussed in [Table format](#table-format)
  above. Default 64 (64 KiB, `kDefaultBlockSize`). Must be at least 4 (4
  KiB — below that a block's fixed zstd frame overhead swamps the payload)
  and at most 16384 (16 MiB, `kMaxBlockSize` — the ceiling `TableReader`
  itself enforces at `open()`, since the reader sizes its decompressed-block
  cache off this value). Out-of-range or non-positive values are rejected
  before anything is written.

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
helpmate probe <FEN> [--tables DIR] [--themes]
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

- `--themes`: also print which named themes (see [Themes](#themes) below) the
  position's optimal solutions show. Opt-in — detection forces solution
  enumeration, work a plain probe does not otherwise pay for:

```
$ helpmate probe "8/7k/5K2/8/8/8/8/6Q1 b - - 0 1" --tables tt --themes
dtm=2 (h#1) count=4
themes: pure model ideal mirror single-piece single-piece:white single-piece:black
```

  A position with no themes prints `themes: (none)`. A color-flipped probe
  (see above) cannot show themes at all — the detectors are hard-coded to the
  black king, so a flipped position's colour-labelled themes would come out
  swapped — and prints `themes: (unavailable: colors were flipped to find a
  table)` instead, still at exit 0.

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
helpmate mine <MATERIAL> --dtm D [--count C] [--starts N] [--ends N] [--theme NAME]... [--max N] [--tables DIR]
```

- `--dtm D` (**required**): exact distance-to-mate, in plies, to match;
- `--count C` (optional): additionally require exactly C optimal solutions;
- `--starts N` (optional): additionally require exactly N *distinct first
  moves* across the optimal solutions — i.e. how many different ways White
  can begin the mate, ignoring how each one finishes;
- `--ends N` (optional): additionally require exactly N *distinct mating
  moves* across the optimal solutions — i.e. how many different final moves
  deliver mate, ignoring how each one got there;
- `--theme NAME` (optional, repeatable): additionally require that at least
  one optimal solution shows theme NAME; every named theme must be shown
  (by some solution, not necessarily the same one). See [Themes](#themes)
  below for the full semantics, the theme list, and the performance caveat —
  theme filters force solution enumeration and cost noticeably more than a
  plain `--dtm`/`--count`/`--starts`/`--ends` scan;
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

## Themes

Since v0.8.0, `mine`, `probe` and the HTTP API can search and annotate by
**theme** — a named, precisely defined property of a mate (`pure`, `model`,
…) or of a solution's moves (`promotion`, `switchback`, …). Naming follows
the [Helpmate Analyzer glossary](https://helpman.komtera.lt/themes.html)
(Viktoras Paliulionis) wherever a name already exists there, so results are
comparable with established practice. `helpmate themes` always prints the
authoritative, in-build list below — read that if this table and the binary
you're running ever disagree.

Sixteen registry entries cover twelve themes. Four themes exist in both a
broad and a colour-specific form (`excelsior`/`excelsior:white`/
`excelsior:black`, `single-piece`/`single-piece:white`/`single-piece:black`)
because a detector only ever answers yes/no — it cannot itself report *which*
side showed the theme, so the colour-specific name is a separate registry
entry rather than an extra output field.

| Theme | Definition |
|---|---|
| `pure` | Every square of the black king's field is unavailable for exactly one reason, and the king's square is attacked exactly once (so double check is impure). |
| `model` | Pure, and every white unit except the king and pawns participates — attacks the king's square or a field square, or stands on one. |
| `ideal` | Model with no exemptions — the white king and white pawns must participate too, and every black unit other than the king must stand on a field square. |
| `mirror` | Every square adjacent to the black king is empty, of either colour. |
| `promotion` | A pawn promotes during the solution. |
| `underpromotion` | A pawn promotes to rook, bishop or knight. |
| `excelsior` | A pawn standing on its own second rank at the start of the solution promotes during it (either colour). |
| `excelsior:white` | Excelsior by a white pawn. |
| `excelsior:black` | Excelsior by a black pawn. |
| `switchback` | A unit leaves a square and returns to it, having visited exactly one intermediate square. |
| `closed-walk` | Rundlauf: a unit returns to its departure square having visited two or more distinct intermediate squares, so it traverses a circuit rather than retracing its path. |
| `self-block` | A black unit other than the king moves onto a square of its own king's field and stands there unattacked in the mating position, blocking a flight square. |
| `single-piece` | Every move by one side is made by the same unit (either side). |
| `single-piece:white` | Every white move is made by the same unit. |
| `single-piece:black` | Every black move is made by the same unit; with the king, this is the Analyzer's "BK moves only". |
| `en-passant` | A ply is an en-passant capture. |

### Match semantics: `any` within a theme, `AND` across themes

A position matches `--theme X` when **at least one** of its optimal solutions
shows theme `X` — not every solution. Naming several themes (`--theme model
--theme self-block`, or `theme=model&theme=self-block` on the API) requires
**all** of them to be shown, but not necessarily by the same solution: a
position with two solutions, one a model mate and the other showing
self-block, matches `--theme model --theme self-block` even though no single
solution shows both. A same-solution ("this one line shows both") variant is
not offered in v0.8.

### The three CLI surfaces

```
helpmate mine <MATERIAL> --dtm N [--theme NAME]...   # repeatable, ANDed
helpmate probe <FEN> --themes                         # annotate one position
helpmate themes                                       # list detectors + their definitions
```

`helpmate themes` prints exactly the table above, generated from the
in-build registry — the vocabulary `--theme` and `--themes` accept is always
discoverable without the docs, and never drifts from the binary.

### The three API surfaces

- `GET /v1/themes` — the registry as JSON, so the dashboard (or any client)
  can build its own theme picker without a hard-coded list:

  ```
  $ curl -s http://127.0.0.1:8642/v1/themes
  {"themes":[{"name":"pure","doc":"Pure mate: ..."}, ...]}
  ```

- `GET /v1/mine` gains a repeatable `theme=` query parameter (same `any`
  within a theme, `AND` across themes semantics as the CLI). An unknown name
  is a `400 invalid_theme` listing every valid name, never silently ignored:

  ```
  $ curl -sG http://127.0.0.1:8642/v1/mine --data-urlencode "material=KQvk" \
      --data-urlencode "dtm=2" --data-urlencode "theme=mirror" --data-urlencode "max=5"
  {"fens":["8/8/8/8/8/8/8/k1KQ4 b - - 0 1", ...],"truncated":true,"skipped_saturated":0}

  $ curl -sG http://127.0.0.1:8642/v1/mine --data-urlencode "material=KQvk" \
      --data-urlencode "dtm=2" --data-urlencode "theme=bogus"
  {"error":{"code":"invalid_theme","message":"unknown theme: bogus","hint":"valid themes: pure, model, ..."}}
  ```

- `GET /v1/probe?fen=…&themes=true` — opt-in (default `false`): detection
  forces solution enumeration, and `probe` is on the dashboard's hot path, so
  a plain probe must not pay for a field most callers never read. On a match,
  the response gains a `themes` array:

  ```
  $ curl -sG http://127.0.0.1:8642/v1/probe --data-urlencode "fen=8/7k/5K2/8/8/8/8/6Q1 b - - 0 1" \
      --data-urlencode "themes=true"
  {"dtm":2,"count":4,"flipped":false,"notation":"h#1",
   "themes":["pure","model","ideal","mirror","single-piece","single-piece:white","single-piece:black"]}
  ```

  For a color-flipped probe, `themes` is `null` (not an empty array — that
  would mean "no themes found") with a sibling `themes_note` explaining why;
  see [Two honest limitations](#two-honest-limitations) below.

### Two things to know before you trust a result

**The solution cap is a false-negative source.** Themes are detected across
a position's optimal solutions, capped at the position's own solution count.
A position whose count is saturated (255+) is never enumerated and never
matches a theme filter; `mine` reports these in its skipped tally rather than
dropping them silently.

**Theme filters are slow on compressed tables.** Detection forces solution
enumeration, which is exactly the random-access pattern that defeats the
block cache — on a compressed table it compounds with the ~6.5x mining
penalty measured in v0.7.5. Mine against raw tables when running theme
searches over large material.

### Performance

Measured on `KQvk`, milliseconds per query (`--tables` on local disk, raw
format):

| Query | ms/query |
|---|---|
| process floor (empty invocation) | 3.12 |
| plain `--dtm` | 4.06 |
| `--starts 1` (enumerates solutions, zero detectors) | 13.12 |
| `--theme mirror` (one detector) | 13.20 |
| four `--theme` flags | 14.46 |

**The detectors cost under 1% of the added work.** The cost is solution
enumeration itself — exactly the work the existing `--starts`/`--ends`
filters already pay, not something the theme feature introduces. On scan
work alone (subtracting the process floor from each number above) a theme
query runs at roughly **10.7x** a plain `--dtm` scan. This compounds with the
~6.5x mining penalty on block-compressed tables measured in v0.7.5 (see
[Table format](#table-format) above), so the practical advice stands: mine
against raw tables for large theme searches.

### Two honest limitations

**Colour-flipped positions cannot be annotated.** When `probe` resolves a
position by flipping colours to find a table (see [Symmetry
reduction](#symmetry-reduction) above), themes are unavailable — every
detector is hard-coded to the black king, so running them on a flipped board
would silently swap the colour-labelled themes (`single-piece:white`/
`:black`, `excelsior:white`/`:black`) and misreport `pure`/`model`/`ideal`/
`mirror` too, since those read from the black king's field specifically. The
CLI prints a note and exits 0; the API returns `"themes": null` with a
`themes_note` field explaining why, distinct from `[]` (no themes found).
Twelve of the sixteen registry entries are in fact flip-invariant and could,
in principle, still be answered — that is a known follow-up, not something
v0.8.0 ships.

**Verification against published problems was deferred by explicit
decision.** The definitions above are this project's own — stated precisely
enough to be argued with, not certified against the Helpmate Analyzer or any
other authority. A detector subtly at odds with composition convention will
return a confident, wrong result, and nothing in this project's test suite
will catch that; only comparison against known compositions would. That
comparison has not been done. Treat every theme match as this codebase's
opinion, not an authoritative ruling.

## `compact` — reclaim disk space in already-unsolvable tables

```
helpmate compact <DIR> [--dry-run] [--compress] [--block-size N]
```

Rewrites every `.hm` table in `DIR` whose cells are **all** unsolvable (or
invalid) into a tiny marker file, reclaiming disk space without changing what
any query can answer. Tables with at least one solvable cell are left
completely untouched, and a table that is already a marker is skipped (not
rewritten again). When a run rewrites nothing at all — every table was either
solvable or already a marker — it prints `already compact`. `--dry-run`
reports what *would* be rewritten and reclaims nothing — it never opens a
file for writing.

With `--compress` (since v0.7.5), `compact` switches to a different mode
entirely: instead of hunting for all-unsolvable tables, it rewrites every
*raw* table in `DIR` as block-compressed at `--block-size` (default 64 KiB;
see [Table format](#table-format) and [`gen`](#gen--generate-tables) above —
in particular, if you actively `mine --count`/`--starts` this table, budget
for ~6.5x slower there regardless of block size), skipping markers and —
always, not just under `--dry-run` — anything written in the last hour, so a
generation run still writing into the same directory is never disturbed.
`--compress` and the marker-compaction mode above are mutually exclusive.

A table that is **already compressed** is handled by comparing its stored
block size against `--block-size`:

- same block size: a true no-op, reported as "already compressed at this
  block size" — nothing is read or rewritten.
- different block size: **re-blocked** in place — decompressed and
  recompressed at the new block size, streaming through a bounded
  decompressed-block cache rather than buffering the whole table (same
  constant-memory approach as a first compression), reported as `re-blocked
  NAME (before -> after)` and counted separately from a first compression in
  the summary line (`N rewritten (X compressed, Y re-blocked)`).

This means **a block size chosen at generation time is not permanent**: a
table compressed at 16 KiB can be moved to 64 KiB (or vice versa) with
`compact --compress --block-size 64` without regenerating it from scratch —
hours for a 5-piece table, over a day for a 6-piece. Re-blocking only ever
changes how a table is *stored*; the decompressed content at every cell is
unchanged (verified: re-blocking a real 462 MiB `KRvkbn` table's 64 KiB
compressed form down to 16 KiB produced a file `md5sum`-identical to
compressing the same raw table directly at 16 KiB).

Do not run `compact --compress` (a first compression or a re-block) inside a
Hugging Face dataset cache directory: rewriting a table's bytes in place
changes its size and sha256 without updating the local `manifest.json`, so
every entry it touches goes stale and the next `pull` silently re-downloads
those files instead of recognizing them as already present.

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
helpmate". Every command that opens a table reports it this way: the query
commands (`probe`, `line`, `mine`, `stats`), `compact`, and both table reads
in `gen` — the `--prune` successor check, which treats it as an error rather
than silently assuming the successor isn't proven dead, and the sub-table load
that cross-material lookups depend on during generation. `probe` is the
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
  progress=False, force_ram=False, compress=False, block_size=64)` —
  generates the closure exactly like the CLI's `gen` (`verbose`/`progress`/
  `force_ram` match `--verbose`/`--progress`/`--force-ram`; reporting goes to
  the process's stderr); returns the list of `.hm` paths written (empty if
  everything already existed). `compress`/`block_size` mirror `gen
  --compress`/`--block-size` (see [Table format](#table-format) above) — same
  unit, too: `block_size` here is **KiB**, exactly like the CLI's
  `--block-size` (`block_size=64` means 64 KiB), even though it is converted
  to raw bytes internally before reaching `GenOptions::block_size`. Earlier
  versions of this binding took raw bytes here while the CLI took KiB; that
  mismatch was a trap (`--block-size 64` on the CLI and `block_size=64` here
  used to produce different tables) and has been fixed by converting in the
  binding, not by documenting around it.
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

Python tests live in `src/packages/bindings/tests/` (`pytest
src/packages/bindings/tests`; add `--run-slow` for the exhaustive
python-chess cross-validation of the full KQvk closure).

## Web dashboard

The browser front end for everything above. It is served by the same process
as the API — there is no second port, no build step, no npm, and nothing is
fetched from a CDN at runtime. Install all three distributions, in
dependency order (`helpmate-api` requires `helpmate`; `helpmate-web` is what
gives the API a dashboard to serve):

```bash
make install
# or: pip install . ./src/packages/api ./src/packages/web
helpmate-server --tables ~/tb --port 8642
# then open http://127.0.0.1:8642/
```

If `helpmate-web` isn't installed (just `helpmate` + `helpmate-api`), the
server still runs but `/` 404s — pass `--web-root DIR` to serve a dashboard
checkout from an arbitrary directory instead, or `--no-web` to say
explicitly that you want the API alone.

Three screens:

- **Explorer** — an interactive board. Drag a piece to play its move, or click
  one from the complete legal-move list, which shows the value each move leads
  to and outlines in green the ones that keep the shortest mate. Below it, the
  optimal lines in SAN, exportable as PGN, and (since v0.8.0) the current
  position's themes — fetched via `probe --themes` (opt-in on the client too),
  showing `themes_note` in place of the list for a color-flipped position
  rather than a blank field. The position is encoded in the URL
  (`/#fen=<urlencoded>`), so every position is a shareable link and the
  browser's back button walks the history.
- **Materials** — every table the server can reach, with piece count, size and
  location (`local` / `cached` / `remote`). Selecting one shows where its
  cells went (solvable / no mate / illegal), a histogram of mate lengths split
  by side to move, a histogram of how many optimal solutions positions have,
  and the deepest sample positions — each clickable into the explorer.
- **Search** — a form over [`/v1/mine`](#get-v1mine), including the `starts` /
  `ends` shape filters and (since v0.8.0) a theme multi-select populated from
  [`/v1/themes`](#get-v1themes), so the picker's vocabulary always matches the
  server's own build rather than a hard-coded list. Results are clickable
  FENs, exportable as a FEN list or CSV. Impossible filter combinations
  (`starts` greater than `count`) are rejected before the request; the server
  stays the authority for the rest.

**Editing a position.** Under the board, a palette places pieces: pick one,
then click squares. `Erase` empties the squares you click, `Clear board`
empties all of them, and the `To move` selector sets the side. While editing,
the board is not probed on every click — a half-built position is illegal by
definition — so click the armed palette entry again (or press `Set`) to
evaluate what you have built. A position with no king, or two of one colour,
says so directly instead of spending a request to be told `invalid_fen`.

**What it needs from the server.** Only the read-only `/v1` routes. Every
contract the API defines is surfaced rather than hidden: `202 fetching` shows
a download-in-progress state and polls, `404` shows the returned `helpmate
gen …` hint, `400` is displayed next to the offending field, and an
unreachable server is reported in the header chip.

Third-party code is vendored, not fetched: **cm-chessboard** 8.7.5 (MIT) lives
under `src/packages/web/helpmate_web/static/vendor/cm-chessboard/` with its
LICENSE and upstream version recorded in
`src/packages/web/helpmate_web/static/vendor/README.md`.

## API server

A small read-only HTTP API (FastAPI + uvicorn) for serving generated tables:
health/catalog/stats, `probe`/`line`/`mine` as JSON, and transparent
on-demand fetching of tables that only live in a remote Hugging Face
dataset. Plus a companion CLI, `helpmate-tables`, for pushing tables to and
pulling them from that dataset.

### Install

```bash
pip install . ./src/packages/api
# or, to also get the dashboard: make install
```

`helpmate-api` requires `helpmate` (the core + CLI + bindings), so it must
install second; nothing is published to PyPI yet, so installing out of
order sends pip looking for the name upstream. This installs `fastapi`,
`uvicorn`, and `huggingface_hub` on top of the base package, and registers
two console scripts: `helpmate-server` and `helpmate-tables`.

### Start the server

```bash
helpmate-server --tables ~/myhelpmate/tables --hf-repo USER/DS \
  --cache ~/.cache/helpmate-tables --port 8642
```

- `--tables DIR` (repeatable): one or more local directories searched, in
  order, for `.hm`/`.stats.json` files. Omit entirely to serve only from the
  remote.
- `--web-root DIR`: serve the dashboard from `DIR` instead of the installed
  `helpmate-web` package (useful for a source checkout of the dashboard
  without installing it).
- `--no-web`: serve the API only — `/` 404s instead of the dashboard. Useful
  when `helpmate-web` isn't installed and you want that to be a deliberate
  choice rather than an unexplained 404.
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

### `GET /v1/themes`

The theme registry — name plus definition for every one of the sixteen
entries in [Themes](#themes) above — served straight from the C++ build so
the dashboard's theme picker never hard-codes a list that can drift from the
binary it's talking to:

```
$ curl -s http://127.0.0.1:8642/v1/themes
{"themes":[{"name":"pure","doc":"Pure mate: every square of the black king's field is unavailable for exactly one reason, and the king's square is attacked exactly once (so double check is impure)."}, ...]}
```

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

`?themes=true` (opt-in) adds a `themes` array; see [Themes](#themes) above
for the full semantics, the flip-fallback limitation (`themes: null` +
`themes_note`), and a real captured example.

### `GET /v1/line`

`?all=true` returns every optimal line instead of just the first.

```
$ curl -sG http://127.0.0.1:8642/v1/line --data-urlencode "fen=8/7k/5K2/8/8/8/8/6Q1 b - - 0 1"
{"lines":[["Kh6","Qh2#"]]}

$ curl -sG http://127.0.0.1:8642/v1/line --data-urlencode "fen=8/7k/5K2/8/8/8/8/6Q1 b - - 0 1" --data-urlencode "all=true"
{"lines":[["Kh6","Qh2#"],["Kh6","Qh1#"],["Kh6","Qg6#"],["Kh8","Qg7#"]]}
```

### `GET /v1/moves`

The position's own value plus **every legal move** with the value it leads
to, in one call. This is what the dashboard's move list is built from: a
browser would otherwise need its own move generator and one `probe` per move.

```
$ curl -sG http://127.0.0.1:8642/v1/moves --data-urlencode "fen=8/7k/5K2/8/8/8/8/6Q1 b - - 0 1"
{"fen":"8/7k/5K2/8/8/8/8/6Q1 b - - 0 1","dtm":2,"count":4,"notation":"h#1","flipped":false,
 "moves":[
  {"uci":"h7h6","san":"Kh6","fen":"8/8/5K1k/8/8/8/8/6Q1 w - - 0 1","dtm":1,"count":3,
   "solvable":true,"optimal":true,"notation":"h#0.5"},
  {"uci":"h7h8","san":"Kh8","fen":"7k/8/5K2/8/8/8/8/6Q1 w - - 0 1","dtm":1,"count":1,
   "solvable":true,"optimal":true,"notation":"h#0.5"}]}
```

(line-wrapped here; the server sends one line.)

- `optimal` is `true` exactly when the move reaches `dtm - 1`, i.e. it keeps
  the shortest mate.
- The list is always the **complete** legal-move list. A move leading to an
  unsolvable position, to a material with no table, or to something no
  tablebase can describe (capturing a king, reachable only from an already
  illegal position) carries `"dtm": null, "solvable": false, "optimal": false`
  rather than being omitted.
- An unsolvable query position reports `"solvable": false` at the top level
  and still enumerates its moves — a composer may want to walk into a
  solvable branch.
- Errors follow `probe`: 400 `invalid_fen`, 404 `unknown_material` with the
  `helpmate gen …` hint, and the 202-fetching contract for remote-only
  material. The color-flip fallback applies too, reported as `"flipped": true`.

### `GET /v1/mine`

Parameters: `material`, `dtm` (required), `count` (optional, exact match),
`starts` / `ends` (optional, exact match on the number of distinct first
moves / distinct mating moves among the optimal solutions — see the CLI
[`mine`](#mine--scan-for-composition-candidates) section for what these mean
and why the golden `8/8/8/8/8/2K5/7Q/1k6 b - - 0 1` position has `starts=2,
ends=4`), repeatable `theme` (optional — see [Themes](#themes) above for the
match semantics, an unknown-name example, and the performance caveat), and
`max`.

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
pip install . ./src/packages/api   # same install as the API server
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
