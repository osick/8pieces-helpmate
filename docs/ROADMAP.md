# Roadmap

Origin: the raw capability notes in `specs/specround_2026_07_29.md`, decomposed
and ordered in the brainstorming session of 2026-07-30. Each rung gets its own
design spec (`docs/superpowers/specs/`) and implementation plan when its turn
comes; this file records the agreed order, goals, dependencies, and open
questions. v0.5.0 (released 2026-07-30) is the baseline: generator to 6
pieces, probe library, CLI, Python bindings, CI, docs.

## v0.6 — Storage + read-only API

**Goal:** tablebase files stored not only locally (Hugging Face dataset +
manifest, sync via CLI tooling), and a read-only FastAPI service exposing
probe / lines / mining / stats / catalog to remote CLI clients and the future
dashboard.

- Design: **approved** — `docs/superpowers/specs/2026-07-30-storage-read-api-design.md`
- Depends on: nothing (baseline v0.5.0)
- Out of scope: pattern/theme search, auth, 7-piece serving
- Open questions: none blocking; S3-compatible backend (B2/R2) optional later

## v0.6.1 — Unsolvable-material prune

**Goal:** never generate or store a material that provably cannot contain a
helpmate, and reclaim the tables already spent on such material.

- Design: **approved** — `docs/superpowers/specs/2026-07-30-unsolvable-material-prune-design.md`
- Plan: `docs/superpowers/plans/2026-07-30-unsolvable-material-prune.md`
- Depends on: v0.6 (marker tables travel through the storage/sync layer)

## v0.6.2 — `mine` starts/ends filters

**Goal:** let `mine` (CLI, HTTP API and Python) select positions by the shape of
their solution set — how many distinct moves the optimal solutions begin with
(`--starts`) and how many distinct moves they mate with (`--ends`). Composition
search leans on exactly this: "four solutions that all start with the same
move", "two solutions converging on one mate".

- Design: **approved** — `docs/superpowers/specs/2026-07-31-mine-starts-ends-filters-design.md`
- Depends on: nothing beyond v0.6
- The last release before the web dashboard.

## v0.7 — Web dashboard

**Goal:** the visible layer — a browser client of the v0.6 read-only API:
position explorer with an interactive board and per-move evaluations, material
browser with stats, mining/composition search with the v0.6.2 shape filters,
and client-side export (FEN/PGN/CSV). Static files served by the existing
FastAPI process; no build step; cm-chessboard vendored. One API addition:
`GET /v1/moves`, which returns every legal move with the value it leads to.

- Design: **approved** — `docs/superpowers/specs/2026-07-31-web-dashboard-design.md`
- Depends on: v0.6 API, v0.6.2 filters
- Delivered beyond the MVP line: the piece palette / free position editing,
  and the mate-length and solution-count histograms in the material browser.
- Verified end-to-end: Playwright + headless Chromium drives a real server in
  CI (`ui` job), alongside `node --test` for the pure helpers. The earlier
  note that Playwright was unusable on the development box was wrong — only
  the driver package was missing.

## v0.7.1 — Package split

**Goal:** reorganise the repo into three independently installable
distributions — `helpmate` (root `pyproject.toml`: C++ core, CLI binary,
Python bindings), `helpmate-api` (`src/packages/api/`), `helpmate-web`
(`src/packages/web/`) — each verifiable on its own, with a single `VERSION`
file every declared version is checked against.

- Design: **approved** — `docs/superpowers/specs/2026-08-01-package-split-design.md`
- Depends on: v0.7 (splits the dashboard and API that already existed)
- No release: a repo-layout rung, not a user-facing one.

## v0.8 — Pattern / theme search

**Goal:** search by theme and pattern, the capability the original notes asked
for. Split out of v0.7 because it needs its own foundations: a definition of
what a "theme" is, a precomputed index per material, generation tooling, and
new query endpoints. Starts with its own brainstorming session.

- Depends on: v0.7 (the UI that will present it), v0.6 storage
- Open questions: the theme taxonomy itself (model, pin, self-block,
  interference, promotion themes...); index format and size; whether themes
  are computed during generation or as a separate pass.

## Unscheduled — Cross-platform CLI builds

Native Windows / macOS / WSL builds and a CI release matrix; formerly bundled
into v0.7. Independent of everything else.

- Open questions: Windows toolchain (MSVC vs MinGW) for the C++20 core.

## v0.9 — Seven pieces ("humongous tablebases", part 1)

**Goal:** the project's namesake research goal. 7-piece slices exceed RAM
(~1.8 TB naive planes — the v0.5.0 RAM guard already computes this), so the
generator needs an out-of-core redesign: disk-backed planes with streaming
passes, partial generation (single sub-slices on demand), checkpoint/resume,
and the deferred perf items (dynamic chunking, thread pool, encode()
allocation elimination). Distributed generation (several machines splitting
a closure) is designed here, delivered incrementally.

- Depends on: nothing functionally; benefits from v0.6 storage for
  distributing finished slices
- Open questions: on-disk pass layout (sequential sweep vs bucketed);
  compression of resident planes; whether distributed-first or
  single-machine-out-of-core-first (recommendation: out-of-core first);
  verification strategy at a scale where exhaustive cross-checks are
  impossible.

## v1.0 — Eight pieces ("humongous tablebases", part 2)

**Goal:** 8-piece generation and serving on distributed infrastructure;
partial/on-demand generation as the primary mode (full 8-piece closures are
compute-years — the value is generating *chosen* slices reproducibly).

- Depends on: v0.9's out-of-core + distributed foundation
- Open questions: hardware budget; which 8-piece materials matter to the
  composition community; public serving economics.

## Exploratory track (parallel, unversioned) — Fairy chess

**Goal:** other stipulations (h=, hs#, ser-h#, …), fairy conditions (Circe,
Madrasi, …), fairy pieces. This changes the move-generation foundation, so it
must not block the main ladder. First step is a feasibility spike: evaluate
Popeye as move generator (its licence, embeddability, speed for tablebase
workloads) vs extending ChessMG — outcome decides everything downstream.

- Depends on: nothing (separate branch of work)
- Open questions: everything — starts with its own brainstorming session.

## Backlog (unscheduled)

### Compression (conditional: performance first)

**Goal:** cut on-disk size, which is the binding constraint on publishing
6-piece sets. **This rung ships only if it does not meaningfully slow
generation or probing** — that condition is the point of the rung, not a
footnote, and the measurements below decide it before any format work starts.

**Why it matters.** Our tables store four uncompressed bytes per cell (DTM and
optimal-line count, both sides to move), over the same position space a
conventional tablebase covers. A 6-piece pawnless slice is 31 GB, one with a
pawn ~91 GB (a pawn breaks the 8-fold symmetry to 2-fold, which outweighs its
48-vs-64 squares), and a 7-piece pawnless slice ~2 TB. Measured on real data:
`zstd -1` — the cheapest setting — compresses a solvable 5-piece slice
(`KBvkrb.hm`, 484.5 MB) to 49.8 MB, a **10.3x** reduction. Higher levels and a
layout-aware encoding would do better, because most cells in a solvable slice
are still unsolvable.

**The hard part is random access, not ratio.** Probing mmaps the file and reads
one byte at a known offset; a plain compressed stream destroys that. So the
candidate design is block-compressed planes (fixed-size blocks plus a block
offset index in the header) with a small decompressed-block cache — random
access preserved, one block decompressed per cold probe.

**Decision spike, before any implementation** — measure on representative
slices (a solvable 5-piece, an unsolvable one, a pawnful one):

1. compression ratio per block size (16/64/256 KB) and level;
2. probe latency, cold and warm, against the uncompressed baseline;
3. sequential-scan throughput (what `mine` and `stats` depend on);
4. generation wall-clock delta — compression happens once at finalize, outside
   the hot loop, so this should be small, but it must be shown, not assumed.

**Ship only if** the ratio is at least ~5x on representative slices, warm probe
latency stays within roughly 2x of uncompressed, and generation slows by no
more than a few percent. **If those thresholds are not met**, fall back to
transport-and-archive compression only: `helpmate-tables push/pull` compresses
for the Hugging Face dataset and decompresses on arrival, so distribution and
cold storage get the full benefit at exactly zero runtime cost. That fallback
is a good outcome, not a failure.

- Depends on: v0.6.1 (whole-slice elimination first — it is strictly cheaper
  than compressing a file that need not exist)
- Open questions: block size and codec (zstd vs lz4 for the latency/ratio
  trade-off); whether the count planes deserve a different encoding from the
  DTM planes; whether a sparse bitmap layout beats generic block compression
  for slices where solvable cells are a small fraction.

## Standing constraints (apply to every rung)

- Correctness first: every new capability ships with the same verification
  rigor as v0.5.0 (independent cross-checks, golden tests, review gates).
- The published table format carries generator_version; format changes bump
  it and stay loadable-or-rejected via the load-time identity checks.
- Max 4 cores for local testing on the development box; heavy generation runs
  are the user's call.
