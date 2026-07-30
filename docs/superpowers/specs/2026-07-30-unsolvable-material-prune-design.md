# Unsolvable-Material Prune (v0.6.1) — Design

Date: 2026-07-30
Status: approved by user (brainstorming session 2026-07-30)
Origin: user observation that 30 of 45 generated slices contain no solution at
all, costing ~34 GB of disk and the generation time behind it.

## Goal

Never spend generation time or disk on a material that provably cannot contain
a helpmate, and reclaim the space already spent on such tables. Correctness is
the hard constraint: pruning must never change a single value in a solvable
slice.

## Background: what makes a slice unsolvable

Every helpmate solution ends in a mate position. That mate lives either in the
slice itself or — after a capture or promotion — in one of its successor
slices. So a slice `S` has no solvable position exactly when:

1. `S` contains no mate position, **and**
2. every direct successor of `S` is itself entirely unsolvable.

Condition 2 is available for free: `Material::closure_topo` generates
successors before their parent, so their status is already known when `S` is
reached.

A second, purely structural case needs no scan at all: if the mating side has
no piece besides its king, it can never give check, so no mate can exist. In
such a material only Black owns pawns, so no promotion can ever add a white
piece — the property holds across the whole closure.

## Known unsolvable classes (test oracles, not generator logic)

The user's classification, confirmed against the 45 generated slices:

- `Kvk*` — any material whose white side is a bare king.
- `KBvk[qr]*` — white king and bishop against black king plus any combination
  of queens and rooks.
- `KNvk[q]*` — white king and knight against black king plus any combination
  of queens.

These are **verification oracles**, not shortcuts in the generator. The derived
rule above establishes unsolvability by exhaustive scan per slice, so it cannot
silently mis-classify a material; a hardcoded pattern that was subtly wrong
would corrupt tables invisibly. Tests assert that the generic rule reproduces
exactly these classes — and that the neighbouring solvable materials
(`KNvkr`, `KNvkqr`, `KBvkrb`, `KBvkqb`, `KBvkb/n/p`, `KNvkb/n/p/bb`) still come
out solvable. A disagreement means a real bug in the rule or in the list.

Rejected on purpose: a structural fast path for the `KB`/`KN` classes that
would skip even the mate scan. It saves one plane-free pass on materials that
are already cheap to dismiss, at the cost of an unverifiable hand-proof.
Revisit only if profiling shows the mate scan dominating 7-piece runs.

## Components

### 1. Structural check (`src/indexing/material.{h,cpp}`)

`bool Material::mating_side_is_bare_king() const` — true when the white side
holds only the king. Used by the generator before any allocation.

### 2. Solvability decision in `generate()` (`src/generator/generator.cpp`)

Per slice, in this order, so that solvable slices pay nothing extra:

1. If `mating_side_is_bare_king()` → unsolvable. No planes, no passes.
2. Else if **all** direct successors are known unsolvable → run a plane-free
   mate scan (decode each cell, both sides to move, test for mate). No mate
   found → unsolvable. No planes are ever allocated in this branch, so the RAM
   guard never trips on a doomed slice.
3. Otherwise → generate normally, unchanged.

Successor status is read from the successor's table header flag (below), so it
survives across runs and does not depend on a slice being regenerated.

`GenOptions` gains `bool prune = true` with a CLI `--no-prune` escape hatch,
used by tests to produce a full table for cell-by-cell comparison.

### 3. Marker tables (`src/format/table_file.{h,cpp}`)

The `.hm` header gains an `ALL_UNSOLVABLE` flag. A marker table carries the
header and JSON metadata but **no payload**: a 31 GB file becomes a few hundred
bytes.

- Writer: `write_unsolvable(path, material, plane_size, stats_json)`.
- Reader: when the flag is set, `get(stm, cell)` returns `DTM_UNSOLVABLE` with
  count 0 for every in-range cell without mmapping anything; `plane_size()` and
  `material_name()` still come from the header, so the load-time identity
  checks added in v0.5.0 keep working; out-of-range cells still throw.
- Format version becomes 2 **only for marker tables**; ordinary tables continue
  to be written as version 1. Readers accept both, so every existing table and
  every existing consumer is unaffected.
- The `.stats.json` sidecar for a marker table reports `max_dtm: 255`, all
  cells unsolvable, and `"all_unsolvable": true`.

### 4. `helpmate compact <dir>` (`src/cli/main.cpp`)

Reclaims space already spent. For each `.hm` in the directory: stream both DTM
planes; if every cell is `DTM_UNSOLVABLE` or `DTM_INVALID`, rewrite the table
as a marker (write to a temp file in the same directory, then rename — never a
partial file in place) and update the sidecar. Tables with any solvable cell
are left untouched.

- `--dry-run` lists what would be rewritten and the space reclaimed.
- Exit codes follow the existing CLI convention (0 ok, 2 usage, 3 error).
- Reads are sequential and the tool is single-threaded: it is safe to run while
  a generation writes *other* slices into the same directory.

### 5. Push-hashing fix (`server/helpmate_server/tables_cli.py`)

Deferred debt from the v0.6 review: `push` currently hashes every file twice
(once in `write_manifest`, once for the remote-manifest merge). Compute
`build_manifest` once and feed both the local write and the merge.

## Behaviour elsewhere: unchanged

Probing a position in an unsolvable slice returns exactly what it returns
today. The probe library, the HTTP API, the manifest format and
`helpmate-tables` need no changes — they simply see much smaller files, which
makes publishing a complete closure practical.

## Testing

- **Unit** — `mating_side_is_bare_king` across pawnless, pawnful and
  bare-king-vs-pawn materials; marker-table write/read roundtrip including
  out-of-range rejection and identity checks; a version-1 table still reads
  correctly (backward compatibility).
- **Oracle** — generate the full 3- and 4-piece closure with pruning on and
  assert the unsolvable set is exactly the materials matching the three classes
  above, and that the listed solvable neighbours are solvable.
- **Equivalence** — for a small unsolvable material (`KBvkq`), generate with
  `--no-prune` and with pruning, and assert every cell of both tables reports
  the same value through the reader. For a solvable material (`KQvk`), assert
  the generated file is byte-identical with and without pruning.
- **Tool** — `compact` on a directory holding a full unsolvable table produces
  a marker whose reads match the original cell for cell; a solvable table is
  left byte-identical; `--dry-run` writes nothing.
- **Regression** — the existing suites (C++, Python, server) stay green.

## Out of scope

Structural shortcuts for the `KB`/`KN` classes (see above); any change to the
solvable-slice generation path; fairy conditions, where these classifications
do not hold.
