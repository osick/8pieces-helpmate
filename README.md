# helpmate

A tablebase generator and query engine for chess **helpmates**.

## What this is

In a helpmate, both sides *cooperate*: Black moves first and helps White deliver
checkmate in the fewest possible moves. Composers publish these as `h#n` problems
("helpmate in n") — a starting position plus a claim that mate is reachable in
exactly `n` Black moves and `n` (or `n−1`) White moves, ideally with a **unique**
solution. Because both sides work toward the same goal, the underlying search is a
plain cooperative shortest-path problem rather than the min/max game tree an ordinary
(competitive) tablebase needs — which is what makes it practical to solve exhaustively
for whole material classes rather than one position at a time. The design rationale is
laid out in full in
[`docs/superpowers/specs/2026-07-19-helpmate-tablebase-design.md`](docs/superpowers/specs/2026-07-19-helpmate-tablebase-design.md).

This project builds, for a given material combination (say `KQvk` — White king and
queen versus Black king), a table covering *every* legal position in that material and
answering, for each one:

- **dtm** — distance to mate, in half-moves (plies), assuming both sides cooperate
  optimally;
- **h#n notation** — the composer's convention, derived directly from dtm: a
  Black-to-move position with dtm `2n` is `h#n`; a White-to-move position with dtm
  `2n+1` is `h#n.5` (White needs one more half-move than Black's `n` full moves to
  deliver the actual mate);
- **count** — the number of *distinct* optimal continuations that reach mate in the
  minimum number of plies. This is the number composers care about for soundness: 1
  means the try has a unique solution, 2+ means it has duals (multiple solutions,
  usually a flaw in a composition).

Take the position `8/7k/5K2/8/8/8/8/6Q1 b - - 0 1` (Black king h7, White king f6,
White queen g1, Black to move) as a concrete example: probing it gives `dtm=2`,
i.e. `h#1` — one Black move, one White move to mate — with `count=4`: four distinct
optimal lines tie for shortest. Black's king can go to h6, after which White has three
different mates (`Qg6#`, `Qh1#`, `Qh2#`), or Black's king can go to h8, after which the
only mate is `Qg7#`. Four lines total, all reaching mate at ply 2, so the tablebase
reports `count=4`, `dtm=2`. This exact position is used as a golden test throughout the
codebase and is reproduced live below.

Everything in the table is computed by exhaustive fixed-point search over the whole
material class (see [Architecture](#architecture)), not per-position search, so once a
material combination is generated, every query against it — probing a position,
listing its optimal lines, or scanning for compositions with a given dtm and solution
count — is an O(1) table lookup, not a fresh search.

## Documentation

- [docs/BUILD.md](docs/BUILD.md) — full build guide: prerequisites, dependency
  fetching (including the offline/pre-seeded `_deps` workflow), every Makefile
  target, coverage, the Python package build, and troubleshooting.
- [docs/USAGE.md](docs/USAGE.md) — full usage guide: table generation, probing,
  optimal lines, the complete `stats.json` field reference, mining, exit codes,
  DTM/h#n semantics, resource guidance per piece count, and the Python API.

## API server and web dashboard

`pip install ".[server]"` adds `helpmate-server` (a read-only HTTP API —
health/catalog/stats/probe/line/moves/mine, with on-demand fetching from a
Hugging Face dataset for tables not stored locally) and `helpmate-tables`
(push/pull tables to that dataset). See the
["API server" section of docs/USAGE.md](docs/USAGE.md#api-server) for every
route, real curl examples, and the manifest format.

The same process serves a **web dashboard** at `/` — an interactive board with
per-move evaluations and optimal lines, a material browser with mate-length
and solution-count histograms, and composition search with the `starts`/`ends`
shape filters. No build step, no CDN: plain ES modules with cm-chessboard
vendored.

```bash
helpmate-server --tables ~/tb --port 8642   # then open http://127.0.0.1:8642/
```

See the ["Web dashboard" section of docs/USAGE.md](docs/USAGE.md#web-dashboard).

## Quick start

### Build

Requires **CMake ≥ 3.24** and a **C++20 compiler — GCC ≥ 13**. On older distributions
where the default `g++`/`cc` predate GCC 13 (this repo was developed on openSUSE Leap,
whose system compiler is too old), point the build at a newer one explicitly:

```bash
CXX=/usr/bin/g++-13 CC=/usr/bin/gcc-13 make test
```

`make test` configures (`cmake -S . -B build`), builds, and runs the fast test suite
via `ctest`. First configure uses CMake `FetchContent` to fetch three header/source
dependencies — [osick/ChessMG](https://github.com/osick/ChessMG) (move generation
core), [Catch2](https://github.com/catchorg/Catch2) (test framework), and
[nlohmann/json](https://github.com/nlohmann/json) (used for the stats sidecar and
Python-facing JSON) — into `build/_deps/`; after that first fetch, rebuilds are fully
offline.

```bash
CXX=/usr/bin/g++-13 CC=/usr/bin/gcc-13 make test
# ...
# 100% tests passed out of 64
```

A handful of exhaustive/multithreaded-determinism tests are tagged `[slow]` (tens of
minutes: full closures, byte-identical N-thread vs 1-thread reruns) and are excluded
from `make test` by default. Run them explicitly with:

```bash
./build/helpmate_tests "[slow]"
```

The CLI binary lands at `./build/helpmate`.

### Step-by-step build (if `make test` gives you trouble)

The three most common failure modes, in the order people hit them:

1. **`cmake: command not found` or CMake too old** — you need CMake ≥ 3.24. If you
   installed a newer CMake per-user (e.g. `pip install cmake` puts it in
   `~/.local/bin`), make sure it's on `PATH` first:

   ```bash
   export PATH="$HOME/.local/bin:$PATH"
   cmake --version   # must report >= 3.24
   ```

2. **Compiler errors mentioning C++20 / `-std=c++20`, or a baffling
   `Could NOT find Threads`** — your default `g++` is too old. Set `CXX`/`CC`
   explicitly:

   ```bash
   export CXX=/usr/bin/g++-13 CC=/usr/bin/gcc-13
   ```

   **Important:** CMake caches the compiler on the *first* configure and ignores
   these variables afterwards. If you already ran `cmake` once without them
   (typical symptom: the cache says `CMAKE_CXX_COMPILER:FILEPATH=/usr/bin/c++`
   and every configure fails with `Could NOT find Threads`, because the old
   compiler can't build the C++20 test program), delete the build tree and
   configure again:

   ```bash
   rm -rf build
   cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
   ```

3. **An SSH passphrase prompt (or hang) during the first configure** — the first
   configure clones the three dependencies from GitHub over HTTPS. If your global
   gitconfig rewrites `https://github.com/` to SSH (`url.…insteadOf`), that clone
   turns into an SSH fetch and asks for your key passphrase. Either enter it once
   (the fetch is cached in `build/_deps/` and never repeated), or bypass your global
   gitconfig for the one configure step:

   ```bash
   GIT_CONFIG_GLOBAL=/dev/null cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
   ```

With those settled, the full sequence is:

```bash
export PATH="$HOME/.local/bin:$PATH"           # if your cmake lives there
export CXX=/usr/bin/g++-13 CC=/usr/bin/gcc-13  # if your default gcc < 13
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release # configure (fetches deps once)
cmake --build build -j"$(nproc)"               # build
ctest --test-dir build --output-on-failure     # fast test suite (optional)
```

### Install

```bash
cmake --install build --prefix "$HOME/.local"  # installs ~/.local/bin/helpmate
helpmate --help                                # works if ~/.local/bin is on PATH
```

Use `--prefix /usr/local` (with `sudo`) for a system-wide install, or simply copy
the single self-contained binary wherever you like:

```bash
install -Dm755 build/helpmate ~/.local/bin/helpmate
```

The Python package is installed separately with `pip install .` — see
[docs/BUILD.md](docs/BUILD.md).

### Coverage

```bash
pip install gcovr   # into whatever Python environment you use for dev tooling
CXX=/usr/bin/g++-13 CC=/usr/bin/gcc-13 make coverage
```

`make coverage` configures a *separate* `build-cov/` tree with `-DHELPMATE_COVERAGE=ON`
(adds `--coverage -O0 -g` to `helpmate_core` only — the normal `build/` tree is
untouched), reuses the dependency sources already fetched under `build/_deps/` (run
`make build` or `make test` at least once first) so it never re-clones anything, runs
the fast suite, and prints a `gcovr` line/function/branch summary plus an HTML report
at `build-cov/coverage/index.html`.

## CLI usage

All five subcommands, run for real against this repo (`--tables` points at a scratch
directory; a real workflow would reuse one directory across all five commands).

**`gen`** — build every table needed for a material class, including sub-slices
reached by captures/promotions:

```
$ helpmate gen KQvk --tables tt
tt/Kvk.hm max_dtm=255
tt/KQvk.hm max_dtm=14
```

(`Kvk` — king vs king, unconditionally unsolvable, `max_dtm=255` — is built first
because a Black king capturing the queen lands there; `KQvk` itself tops out at
`max_dtm=14`, i.e. the longest optimal helpmate in this material is `h#7`.)

**`probe`** — look up one position:

```
$ helpmate probe "8/7k/5K2/8/8/8/8/6Q1 b - - 0 1" --tables tt
dtm=2 (h#1) count=4
```

**`line`** — print one optimal line (SAN); `--all` prints every optimal line:

```
$ helpmate line "8/7k/5K2/8/8/8/8/6Q1 b - - 0 1" --tables tt
Kh6 Qh2#

$ helpmate line "8/7k/5K2/8/8/8/8/6Q1 b - - 0 1" --tables tt --all
Kh6 Qh2#
Kh6 Qh1#
Kh6 Qg6#
Kh8 Qg7#
```

**`stats`** — generation-time statistics for a material class (dtm histogram, a
uniqueness histogram — how many positions at each dtm have exactly 1, 2, … optimal
solutions — deepest positions, deepest *uniquely*-solved positions):

```
$ helpmate stats KQvk --tables tt
{
  "material": "KQvk",
  "max_dtm": 14,
  "plane_size": 29568,
  "cells": { "invalid": {...}, "unsolvable": {...} },
  "dtm_histogram": { "wtm": {...}, "btm": {...} },
  "uniqueness": { "wtm": {...}, "btm": {...} },
  "deepest": [ "8/6k1/5Q2/8/8/8/8/K7 b - - 0 1", ... ],
  "deepest_unique": [ "8/8/7k/6Q1/8/8/8/K7 b - - 0 1", ... ],
  ...
}
```

(output truncated above for readability; the real command prints the complete JSON)

**`mine`** — scan a material class for composition candidates: positions matching an
exact dtm and (optionally) an exact solution count:

```
$ helpmate mine KQvk --dtm 2 --count 1 --max 3 --tables tt
8/8/8/8/8/8/8/k1KQ4 b - - 0 1
8/8/8/8/8/2Q5/8/k1K5 b - - 0 1
8/8/8/8/4Q3/8/8/k1K5 b - - 0 1
```

(three `h#1` positions with a *unique* solution — good raw material for a sound
one-line helpmate composition)

`--starts N` / `--ends N` (v0.6.2) narrow the scan further, to an exact number of
distinct first moves / distinct mating moves among the optimal solutions — see
[USAGE.md](docs/USAGE.md#mine--scan-for-composition-candidates) for the full
semantics and a worked dual-shape example.

**`compact`** — rewrite already-fully-unsolvable tables (e.g. ones built before v0.6.1
added pruning at generation time) as tiny marker files, reclaiming disk space with no
change in queryable results; see [USAGE.md](docs/USAGE.md#compact--reclaim-disk-space-in-already-unsolvable-tables)
for a worked example.

Full usage/help text (`helpmate --help`) documents every flag and exit code
(`0` success — including a reported "unsolvable" — `2` a required table is missing and
which `helpmate gen` command builds it, `3` bad usage/unparseable input).

## Python API

```bash
pip install .            # or: pip install -e .[dev] for the pytest/python-chess dev extras
```

Packaging is via [scikit-build-core](https://github.com/scikit-build/scikit-build-core)
and pybind11 — `pip install` runs its own CMake configure (with `-DHELPMATE_PYTHON=ON`)
and compiles the same `helpmate_core` C++ library into an extension module.

```python
import helpmate

# build (or reuse, if already built) every table this material class needs
helpmate.generate("KQvk", tables="tables/", threads=4)

tb = helpmate.Tablebase("tables/")

dtm, count, flipped = tb.probe("8/7k/5K2/8/8/8/8/6Q1 b - - 0 1")
# dtm=2, count=4, flipped=False

tb.line("8/7k/5K2/8/8/8/8/6Q1 b - - 0 1")
# ['Kh6', 'Qh2#']

tb.lines("8/7k/5K2/8/8/8/8/6Q1 b - - 0 1", max=10)
# [['Kh6', 'Qh2#'], ['Kh6', 'Qh1#'], ['Kh6', 'Qg6#'], ['Kh8', 'Qg7#']]

list(tb.mine("KQvk", dtm=2, count=1, max=3))
# ['8/8/8/8/8/8/8/k1KQ4 b - - 0 1', '8/8/8/8/8/2Q5/8/k1K5 b - - 0 1', ...]

tb.stats("KQvk")["max_dtm"]
# 14
```

`tb.probe()` returns `None` for a legal but unsolvable position, and raises
`helpmate.MissingTableError` (a `RuntimeError`) if the position's material has no
generated table and no usable color-flip fallback — the message names the exact
`helpmate gen` invocation that would build it. Malformed FENs/material strings raise
`ValueError`.

**Dev note — building from a fresh clone on a machine that rewrites GitHub HTTPS URLs
to SSH** (e.g. via `insteadOf` in `.gitconfig`, which otherwise pops up an SSH
passphrase prompt during `pip install`'s own CMake configure): pre-seed the same
`FETCHCONTENT_SOURCE_DIR_*` overrides `make coverage` uses, pointing at whatever
`build/_deps/*-src` you already have from an ordinary C++ build:

```bash
SKBUILD_CMAKE_ARGS="-DFETCHCONTENT_FULLY_DISCONNECTED=ON;\
-DFETCHCONTENT_SOURCE_DIR_CHESSMG=$PWD/build/_deps/chessmg-src;\
-DFETCHCONTENT_SOURCE_DIR_CATCH2=$PWD/build/_deps/catch2-src;\
-DFETCHCONTENT_SOURCE_DIR_JSON=$PWD/build/_deps/json-src" \
  pip install -e .[dev]
```

(run an ordinary `make build` first so `build/_deps` is populated; scikit-build-core's
configure is otherwise entirely separate from the plain-CMake `build/` tree.)

## Table format

Each material class is one file, `tables/<SLICE>.hm` (e.g. `tables/KQvk.hm`): a 64-byte
fixed header (magic, version, canonical material name, symmetry kind, index plane
size, max dtm) followed by a length-prefixed JSON metadata blob, followed by four
memory-mappable byte planes — DTM-white-to-move, DTM-black-to-move,
count-white-to-move, count-black-to-move — one byte per index cell, sentinel `255` for
unsolvable/invalid cells. `TableReader`/`TableWriter` (mmap-backed, atomic
write-then-rename) are the whole implementation; see
[`src/format/table_file.h`](src/format/table_file.h) for the exact layout.

## Architecture

- **Indexing** (`src/indexing/`): each position maps to a dense integer index within
  its material's plane via a symmetry-reduced mixed-radix scheme. Both kings are
  indexed jointly through a precomputed non-adjacent-kings table — 1806 states for
  slices with pawns (left-right mirror symmetry only, since pawns break diagonal
  symmetry), 462 for pawnless slices (full 8-fold board symmetry, White king
  restricted to the a1-d1-d4 triangle). Every other piece indexes ×64 (×48 for a pawn,
  ranks 2-7 only — pawns never index rank 1/8). En passant is *not* indexed: whenever
  a double pawn push next to an enemy pawn is reachable, its value is folded in as
  `min(table value, 1 + value of the EP-capture successor)`, looked up in whatever
  (necessarily different-material) sub-slice table the EP capture lands in. Castling
  is out of scope entirely — no castling rights ever appear in any FEN this project
  reads or writes.
- **Generation** (`src/generator/`): for material `M`, first compute the closure of
  every sub-slice reachable via a capture or promotion (topologically sorted, built
  before `M` itself, since `M`'s forward-scan needs their tables to look up capture/
  promotion successors), then run an init pass (mark invalid cells; mark dtm=0 for
  every Black-to-move checkmate) followed by forward-scan fixed-point passes: pass
  `d` scans still-unresolved cells, generates their legal moves, and assigns `dtm=d`
  to any cell with a successor at `dtm=d-1`; passes stop when one assigns nothing. A
  second sweep in increasing dtm order computes the optimal-line count per cell
  (`count(p) = Σ count(s)` over exactly the successors achieving the minimal dtm,
  saturating at 255). Both sweeps parallelize over the index range across worker
  threads: pass `d` only ever writes into cells that are still unresolved and only
  ever reads values below `d`, so there is no read/write race between threads working
  on different chunks of the same pass, and multithreaded output is required to be
  byte-identical to single-threaded output (enforced by tests).
- **Storage/probing** (`src/format/`, `src/probe/`): tables are written atomically
  (temp file + rename) and read back via mmap, so probing a huge table costs a page
  fault, not a full load. `Tablebase` lazily loads and caches whatever slices a query
  touches, reconstructs optimal lines by greedy descent through the dtm planes (with
  the same EP adjustment applied during descent), and falls back to a color-flip of
  the position when only the flipped slice was generated (e.g. probing `KvkQ` when
  only `KQvk` was built) — reflecting the reduced index's built-in "White always
  delivers mate" canonicalization.

## Verification story

Because the entire point of a tablebase is that its answers are trustworthy, this
project leans hard on independent cross-checks rather than trusting the generator to
grade its own homework:

- **An independent oracle.** `src/generator/oracle.cpp` is a from-scratch cooperative
  iterative-deepening DFS solver that shares only the move generator with the
  fixed-point generator — no shared indexing, no shared search structure. It re-solves
  sampled positions from every generated slice, checking both dtm *and* the number of
  optimal lines (which it enumerates itself, capped at 255), and any mismatch fails
  the build.
- **Exhaustive python-chess cross-validation — a third, wholly independent
  implementation.** `tests/python/test_crosscheck.py::test_exhaustive_kqvk` (marked
  `slow`, run with `--run-slow`) enumerates *every one* of the 368,452 legal `KQvk`
  positions, runs a plain forward-scan BFS written directly against
  [python-chess](https://python-chess.readthedocs.io/) (no helpmate code involved in
  computing the reference values), and asserts agreement with `tb.probe()` on both
  dtm and optimal-line count for every single position, in both directions (no
  reference-solvable position reported unsolvable by the tablebase, and vice versa).
  The default (non-`slow`) suite still exercises the same movegen/perft
  cross-validation on 200 random positions and 25 random perft(3) roots every run.
- **Byte-identical multithreaded determinism.** Generation is required to produce
  identical output files whether run with 1 thread or N; this is asserted directly
  (including on `KPvkp`, a material class where en passant successors are actually
  reachable, so the multithreading story is exercised on the one code path — the EP
  two-ply lookup — whose safety depends on values already written by another slice/
  thread).
- **Golden compositions.** Known-answer positions (including the `KQvk` example
  above) are checked exactly, including their full set of optimal lines, not just
  their dtm.

## Coverage

Measured with `make coverage` (gcovr, GCC `--coverage` instrumentation, fast suite
only, on `helpmate_core`'s sources under `src/`): **91.6% line coverage** (741/809
lines), 97.2% function coverage, 61.8% branch coverage. The full per-file HTML report
is at `build-cov/coverage/index.html` after running `make coverage`.

The biggest measured gaps: `src/format/table_file.cpp` (85%) and `src/chess/board.cpp`
(90%) — mostly defensive error paths for malformed/truncated table files and rare
hash/copy edge cases; `src/generator/parallel.h` (68%) — the per-worker
exception-propagation path, which by design only runs when a worker thread throws,
not exercised by the happy-path tests; `src/generator/eval.h` (50% by gcov's line
count, but see caveat below).

Caveat worth stating plainly rather than hiding: `eval.h`'s en-passant branch and
`parallel.h`'s hot loops are both exercised by dedicated tests with exact value
assertions (`test_generator_pawns.cpp`'s "eval_board combines EP branch with table
value" calls `eval_board` directly and checks its returned dtm/count for both a
clear-winner and a tied-count case) and by real KPvk/KPvkp generation runs under
multiple threads — but GCC's `--coverage` counters are not thread-safe (a known
upstream limitation, gcc.gnu.org/bugzilla/show_bug.cgi?id=68080: concurrent
non-atomic increments to the same line counter from multiple threads can corrupt or
lose hits). This run's raw gcov output contained "suspicious hit"/negative-hit
warnings on exactly the hot, multithreaded-generator-loop lines in `board.cpp`
(silenced with `--gcov-ignore-parse-errors=all` to let gcovr complete), which is
consistent with some genuinely-executed lines in the template-heavy, multithreaded
`eval.h`/`parallel.h` code losing their counters to the same tool limitation rather
than never having run. Net effect: the reported 91.6%/97.2%/61.8% numbers are honest
and unmodified gcovr output, comfortably above the 80% line-coverage bar either way,
but the two lowest-scoring files specifically should be read with that caveat rather
than as "half the logic is untested."

Earlier coverage runs also hit a known, separately-tracked issue: a pre-existing
heap corruption bug in the root-slice generation scan (manifesting as a SIGSEGV in
one run and a `map::at` exception in another, on different `test_probe.cpp` cases
each time — same signature independently diagnosed for a user-reported 5-piece
`KNvkqr` crash, also mentioned under [Limits](#limits) below). It is intermittent:
across four full `make coverage` attempts, two hit this bug (on a different
`test_probe.cpp` test each time) and two completed with all 64 fast-suite tests
passing cleanly end to end — including the run that produced the 91.6%/97.2%/61.8%
numbers quoted above (one unbroken `cmake` configure → build → `ctest` → `gcovr`
log, no separate/unlogged steps). The affected tests pass reliably and repeatedly in
the normal (`-O2`) build; the fix is tracked as a separate follow-up task and
intentionally not addressed here.

## Limits

- **Materials**: any combination of the six piece types on both sides (2-8 pieces
  total including both kings); castling is never supported (no FEN with castling
  rights is accepted); the 50-move rule is ignored (irrelevant to a cooperative
  shortest-path value — a helpmate solution is always shorter than 50 moves in
  practice); en passant is exact.
- **Practical scaling**: 3-4 piece classes generate in under a couple of seconds
  (measured ~0.6s for `KQvk`); 5-piece classes take minutes to a couple of hours
  depending on material (still 1 byte/cell, 4 planes, no compression); 6-piece
  classes are feasible but heavy — roughly 14-28 GB of table storage/RAM and
  multi-day generation runs at the current 1-byte/cell, uncompressed,
  non-deduplicated encoding. 7-8 piece classes are out of scope for this version;
  the storage format's versioned encoding field and the slice-DAG generation order
  are deliberately designed so a future out-of-core/compressed encoding can be added
  without invalidating already-generated tables. **5-piece generation currently has
  a known, intermittent crash bug** (heap corruption in the root-slice generation
  scan; tracked separately and being fixed — see the caveat in
  [Coverage](#coverage) above for what's been observed so far).
- **Slow tests**: the full-closure and multithreaded-determinism tests tagged `[slow]`
  (tens of minutes each) are excluded from `make test` and from `pip install`'s default
  test run; run them explicitly (`./build/helpmate_tests "[slow]"`,
  `pytest tests/python --run-slow`) when you want that level of assurance for a new
  material class or after touching the generator.
