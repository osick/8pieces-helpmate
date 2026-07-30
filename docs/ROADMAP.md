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

## v0.7 — Web dashboard + cross-platform CLI

**Goal:** the visible layer. Browser dashboard against the v0.6 API: browse
materials, probe positions (board UI), mining, **pattern/theme search** (needs
its own precomputed index — designed in this rung), export (FEN lists, PGN,
CSV). Reference implementation to study: niklasf/syzygy-tables.info. CLI
grows: search subcommands against the API, report generation, and native
Windows / macOS / WSL builds (CI release matrix).

- Depends on: v0.6 API
- Open questions: index design for themes/patterns (what is a "theme" —
  needs its own brainstorming); dashboard hosting; board-UI library choice;
  Windows toolchain (MSVC vs MinGW) for the C++20 core.

## v0.8–v0.9 — Seven pieces ("humongous tablebases", part 1)

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

- Depends on: v0.8/0.9 out-of-core + distributed foundation
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

## Standing constraints (apply to every rung)

- Correctness first: every new capability ships with the same verification
  rigor as v0.5.0 (independent cross-checks, golden tests, review gates).
- The published table format carries generator_version; format changes bump
  it and stay loadable-or-rejected via the load-time identity checks.
- Max 4 cores for local testing on the development box; heavy generation runs
  are the user's call.
