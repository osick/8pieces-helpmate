# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
version numbers follow [Semantic Versioning](https://semver.org/) (0.x: minor
bumps may change behavior).

## [Unreleased]

Nothing yet. Add entries here under **Added** / **Changed** / **Fixed** /
**Removed** as changes land; move them into a new version section on release.

## [0.5.0] - 2026-07-30

Initial release.

### Added

- **Tablebase generator** for helpmate (cooperative mate) chess endgames:
  exhaustive fixed-point search over whole material classes (any combination
  of the six piece types, 2-8 pieces, underpromotions and exact en passant
  included; castling out of scope), computing distance-to-mate and the number
  of distinct optimal lines per position. Builds the full capture/promotion
  sub-slice closure in topological order; multithreaded (`--threads`), with
  byte-identical output to single-threaded runs (enforced by tests).
- **Compact, mmap-backed table format** (`.hm`): four 1-byte planes per slice
  (dtm/count x side-to-move) behind a versioned header plus a JSON metadata
  blob, written atomically; a `.stats.json` sidecar per slice (dtm histogram,
  uniqueness histogram, deepest and deepest-uniquely-solved positions).
- **Probe library and CLI** (`helpmate`): `gen`, `probe`, `line` (one or all
  optimal SAN lines), `stats`, and `mine` (scan a class for composition
  candidates by exact dtm/solution count); color-flip fallback for probes,
  clear exit codes, `--version`.
- **Progress and verbosity for `gen`**: `--verbose` per-slice lifecycle lines
  and `--progress` per-pass heartbeat on stderr (stdout stays scriptable),
  with zero hot-loop overhead.
- **RAM guard for `gen`**: refuses, before allocating anything, a slice whose
  planes exceed `MemAvailable`, costing the whole closure upfront;
  `--force-ram` overrides.
- **Python bindings** (`pip install .`, pybind11 + scikit-build-core):
  `helpmate.generate()` and `helpmate.Tablebase` (probe/line/lines/mine/stats).
- **Verification suite**: an independent cooperative-DFS oracle re-solving
  sampled positions from every generated slice; exhaustive python-chess
  cross-validation of the full KQvk class (368,452 positions, dtm and count);
  golden compositions; multithreaded-determinism tests; 6-piece index
  roundtrip tests.
- **Hardened generator lookup paths** (bug #21): every cross-slice/EP lookup
  failure surfaces as a contextual `GeneratorLookupError` (slice, cell, depth,
  FEN) instead of undefined behavior or a bare `map::at`.
- **CI and docs**: GitHub Actions pipeline (build + fast suite + tag release),
  detailed build (`docs/BUILD.md`) and usage (`docs/USAGE.md`) guides,
  coverage tooling (`make coverage`, 91.6% line coverage on `src/`).
