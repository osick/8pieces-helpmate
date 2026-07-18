# Helpmate Tablebase — Design

Date: 2026-07-19
Status: Draft for review

## Goal

Build a tablebase generator and probing toolkit for chess **helpmates**: for a given
material combination (e.g. `KBkqrbp` — White K+B versus Black k+q+r+b+p), compute for
every legal position the smallest number of plies to a position where **Black is
checkmated**, with both sides cooperating.

Because play is cooperative, the value function is a plain shortest path on the game
graph — `dtm(p) = 1 + min over successors dtm(s)` — with no min/max alternation. This
makes generation far cheaper than ordinary distance-to-mate tables.

Target: a correct, well-tested engine validated on 3–5 piece combinations first, with
an index/storage design that scales toward 6+ pieces (RAM permitting) and leaves
8-piece slices to a future out-of-core extension. A full 8-piece slice has ~10^14
placements (tens of TB); v1 does not attempt it in one pass.

## Decisions (agreed during brainstorming)

| Topic | Decision |
|---|---|
| Scale | Scalable engine, validated on small combos first |
| Value convention | DTM in **plies**, goal "Black is checkmated", both side-to-move planes stored |
| Material transitions | Full dependency closure: sub-slices for captures and promotions are built first |
| Rules | En passant exact; castling ignored; 50-move rule ignored |
| Algorithm | Forward-scan fixed-point passes; predecessor-bitmap frontier as later optimization |
| Stack | C++20 core (CMake), pybind11 Python bindings, CLI, stats reports |

## Value semantics

- A **slice** is a material multiset, normalized so that White is the side delivering
  mate. Piece strings use uppercase for White, lowercase for Black: `KBkqrbp`.
  Canonical slice name in files: `KBvkqrbp` (`v` separates the sides).
- Terminal positions: Black to move, in check, no legal moves → **DTM 0**.
- Each slice stores two planes: White-to-move and Black-to-move. Black-to-move values
  are even, White-to-move values odd.
- Orthodox problem notation falls out directly: a Black-to-move position with DTM 2n
  is an `h#n`; a White-to-move position with DTM 2n+1 is an `h#n.5`.
- Positions with no cooperative path to mate (including stalemates and dead material)
  → sentinel **255 = unsolvable**. Illegal index cells (piece overlap, adjacent kings,
  pawn on rank 1/8, side not to move already giving check) → same sentinel space,
  flagged invalid during init.

## Architecture

C++20, CMake, four core libraries plus two thin frontends:

1. **`chess`** — board representation and legal move generation. Piece list + 64-square
   mailbox with precomputed attack tables. Implements check/checkmate/stalemate
   detection, en passant, promotions (to Q/R/B/N). No castling anywhere.
2. **`indexing`** — bijection position ⇄ dense index inside a slice; symmetry
   canonicalization; the material-slice DAG (which sub-slices are reachable via
   captures/promotions).
3. **`generator`** — the forward-scan BFS engine: dependency resolution, DTM array
   allocation, passes to fixed point, multithreaded over index ranges, table file
   writing, stats computation.
4. **`probe`** — loads/mmaps table files; `dtm(position)`; optimal line reconstruction
   by greedy descent; stats reading.

Frontends: `helpmate` CLI and a `helpmate` Python module (pybind11), both thin
wrappers over `generator`/`probe`.

## Indexing

- **Symmetry**: slices containing pawns → left-right mirror only (white king
  canonically on files a–d). Pawnless slices → standard 8-fold board symmetry (white
  king in the a1–d1–d4 triangle). Reduction factor ~2 / ~8.
- **Index layout** = mixed radix, most significant first:
  - both kings jointly via the standard non-adjacent-kings encoding
    (1806 states with pawns, 462 pawnless),
  - each non-king, non-pawn piece: ×64,
  - each pawn: ×48 (ranks 2–7).
- **v1 simplifications** (accepted index waste, revisit for 6+ pieces):
  - identical pieces are not combinatorially deduplicated (~2× waste per identical pair),
  - overlapping-square placements are indexed but marked invalid at init.
- **En passant is not indexed.** The tables cover EP-less positions. Whenever
  generation or probing evaluates a successor created by a double pawn push with an
  adjacent enemy pawn, the successor's effective value is
  `min(table_value, 1 + value(position after each legal EP capture))`.
  EP captures change material, so their results are probed in sub-slice tables.
  This is exact and adds no index states.

Approximate sizes (with-pawns figures, per slice, 1 byte/cell, 2 planes):
3 pieces ≈ 0.2 MB · 4 ≈ 15 MB · 5 ≈ 900 MB · 6 pieces ≈ 55 GB → needs
nibble-packing/identical-piece dedup or the out-of-core extension.

## Generation

`helpmate gen KBkqrbp`:

1. **Dependency closure.** Enumerate all slices reachable via captures and promotions
   (promotion successors before pawn-parents), topologically sort, build missing ones
   first. Slices without cooperative mating potential still get built and come out
   all-unsolvable.
2. **Init pass.** Mark invalid cells; mark DTM 0 for every Black-to-move checkmate.
3. **Forward-scan passes.** Pass d = 1, 2, … scans unresolved cells of matching
   parity; generate legal moves; look up successor values in this slice's array or in
   sub-slice tables (captures/promotions), applying the EP adjustment. If some
   successor has value d−1, assign d. Stop when a pass assigns nothing.
4. **Optimization stage** (later, output-identical): a candidate bitmap — when a cell
   receives value d, mark approximate predecessors (reverse piece moves; a superset is
   fine) so pass d+1 scans candidates only. Correctness never depends on bitmap
   exactness because every candidate is re-verified by forward move generation.
5. **Finalize.** Remaining unresolved → unsolvable; compute stats; write file
   atomically (temp file + rename).

Parallelism: index range split across N threads per pass. Race-free because pass d
only writes d into unresolved cells and only reads values < d.

## Storage format

`tables/<SLICE>.hm`, e.g. `tables/KBvkqrbp.hm`:

- **Header**: magic `HM8P`, format version, material string, symmetry kind, index
  layout parameters, payload encoding id, max DTM, per-distance counts, generator
  version, build timestamp.
- **Payload**: plane wtm, then plane btm; encoding v1 = 1 byte/cell. Nibble packing
  and zstd block compression are future encodings selected via the header; probe
  supports whatever encodings exist.
- **Sidecar** `tables/<SLICE>.stats.json`: distance histogram, unsolvable counts,
  deepest positions as FENs — so reports never rescan the binary table.

## Interfaces

CLI:

```
helpmate gen KBkqrbp [--tables DIR] [--threads N]
helpmate probe "FEN"      # DTM in plies + h#n notation, or "unsolvable"
helpmate line  "FEN"      # one optimal helpmate line in algebraic notation
helpmate stats KBkqrbp    # histogram, unsolvable %, deepest positions
```

Python (pybind11, packaged with scikit-build-core so `pip install -e .` works):

```python
import helpmate
tb = helpmate.Tablebase("tables/")
tb.probe(fen)          # -> int plies, or None if unsolvable
tb.line(fen)           # -> list[str] moves
tb.stats("KBkqrbp")    # -> dict
helpmate.generate("KBkqrbp", tables="tables/", threads=8)
```

FEN strings are the interchange format; no hard dependency on python-chess.

Error handling: missing table → actionable "run `helpmate gen …`" (CLI exit code 2,
Python exception); malformed FEN or material string → validation error naming the
offending token; a position is probed only after normalization maps its material onto
an existing slice, otherwise reported explicitly.

## Testing & verification

- **Unit tests** (Catch2 via CTest): movegen perft counts cross-checked against
  python-chess on random few-piece positions; index ⇄ position round-trips covering
  every symmetry class; file header round-trip.
- **Oracle cross-check**: an independent cooperative IDDFS solver (shares only the
  movegen) re-solves thousands of sampled positions per generated slice; any mismatch
  fails the build.
- **Golden tests**: published 3–4 piece helpmate compositions with known h#n values
  must probe exactly.
- **Exhaustive tiny-slice check**: 3-piece slices fully compared against a brute-force
  BFS over the raw, unindexed position graph.
- **Coverage**: gcov/lcov ≥ 80% on core libraries (`make coverage`); pytest smoke
  tests for the Python bindings.

## Out of scope (v1)

- Full 8-piece slice generation (needs out-of-core streaming; the format and slice
  DAG are designed so this can be added without breaking existing tables).
- Castling, 50-move rule, underpromotion-restricted conventions, fairy pieces.
- Web UI board viewer.
- Table compression beyond the versioned-encoding hook.
