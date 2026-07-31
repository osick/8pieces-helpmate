# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
version numbers follow [Semantic Versioning](https://semver.org/) (0.x: minor
bumps may change behavior).

## [0.6.2] - 2026-07-31

### Added

- **`mine` shape filters, `--starts`/`--ends`**: narrow a `mine` scan to
  positions with an exact number of distinct first moves (`--starts N`) and/or
  distinct mating moves (`--ends N`) among their optimal solutions, on top of
  the existing exact `--dtm`/`--count` match — enough to distinguish, say, a
  4-solution position with 2 tries that each finish 2 ways (`starts=2,
  ends=4`) from one with 4 completely independent lines (`starts=4, ends=4`).
  Available on all three surfaces:
  - CLI: `helpmate mine <MATERIAL> --dtm D [--count C] [--starts N] [--ends N]`.
    Both must be `>= 1` and, when `--count` is also given, `<= --count`;
    violating either is a usage error (exit 3), including a literal `-1`
    (otherwise a value the flags could take, so it can't be treated as
    "unset"). `mine` now also tallies positions it had to skip because their
    stored solution count is saturated (255+, unenumerable — see below) and
    prints the count to stderr on exit.
  - HTTP API: `GET /v1/mine` gains optional `starts`/`ends` query params
    (same exact-match, same `>= 1`/`<= count` validation, `400
    invalid_filter` on violation) and every response gains a
    `skipped_saturated` integer field with the same meaning as the CLI's
    stderr tally.
  - Python: `Tablebase.mine` gained `starts`/`ends` parameters; a new
    `Tablebase.mine_with_stats` returns `(fens, skipped_saturated)` for
    callers that want the tally (the plain `mine` return shape is
    unchanged).
  See [USAGE.md](docs/USAGE.md#mine--scan-for-composition-candidates) and
  [USAGE.md](docs/USAGE.md#get-v1mine) for worked examples.
- **`Tablebase::mine` takes a `MineFilter`**: the `dtm`/`count`/`starts`/`ends`
  scan criteria are now grouped into one `MineFilter{dtm, count, starts,
  ends}` struct instead of separate parameters, with `starts`/`ends`
  evaluated (via the new pure `shape_of(count, lines)` helper, also exposed
  as `Tablebase::solution_shape(fen)`) only for candidates that already
  passed `dtm`/`count` — no wasted work enumerating lines for positions that
  were never going to match. `shape_of` reports `exhaustive: false` instead
  of a `starts`/`ends` count when the stored solution count is saturated,
  which is what lets `mine` (and the API/CLI tallies above) recognize and
  skip those positions instead of guessing at an undercount.

### Fixed

- **A table written by a newer helpmate now reports "upgrade this build",
  not "no table"**: `TableReader::open` gained an `OpenError` out-parameter
  (`NotFound` / `Unreadable` / `UnsupportedVersion`) so callers can tell a
  genuinely missing/corrupt table apart from one whose format `version` this
  build doesn't understand yet. `Tablebase::load` now throws a distinct,
  actionable error for the latter case (`table ... was written by a newer
  helpmate (unsupported table format version); upgrade this build`) instead
  of the same generic "missing table" diagnosis it used to give both cases.

## [0.6.1] - 2026-07-30

### Added

- **Prune provably-unsolvable slices at generation time**: `gen` now skips
  writing a full table for a slice it can prove contains no helpmate at all —
  either the mating side (White, by the index convention) is a bare king
  (`Material::mating_side_is_bare_king()`, e.g. `Kvk`, `Kvkq`, `Kvkr`), or
  every successor slice reached by a capture/promotion is itself already
  proven dead and the slice has no checkmate position of its own
  (`slice_has_any_mate()`). Enabled by default (`GenOptions::prune`, default
  `true`); an oracle test pins the project's known-unsolvable classes.
- **Marker tables (format version 2)**: a pruned slice is written as a tiny
  marker — header + JSON metadata only, no value planes at all — instead of
  a full-size table of all-`DTM_UNSOLVABLE` cells. Every cell of a marker
  reads back as unsolvable when probed, identically to a fully-generated
  all-unsolvable table. `TableReader` accepts both version 1 (ordinary
  tables) and version 2 (markers) transparently; no reader needs to change.
- **`helpmate compact <DIR> [--dry-run]`**: rewrites existing all-unsolvable
  `.hm` tables (e.g. ones generated before this release) into version-2
  markers in place, atomically, reclaiming disk space with no change in
  queryable results. Tables with any solvable cell, and tables that are
  already markers, are left untouched; `--dry-run` is a true no-op that only
  reports what would be rewritten. See [USAGE.md](docs/USAGE.md#compact--reclaim-disk-space-in-already-unsolvable-tables)
  for a worked example.

### Fixed

- **`helpmate-tables push` hashed every file twice**: the local
  `manifest.json` build and the remote-manifest merge each independently
  called `build_manifest`, so every push sha256-hashed the whole `--tables`
  directory twice. Now hashed once and reused for both the local manifest
  write and the merge — real time saved at 6-piece table sizes, no change in
  the manifest's content.

## [0.6.0] - 2026-07-30

### Added

- **`server` extra and `helpmate_server` package** (`pip install ".[server]"`,
  adds `fastapi`, `uvicorn`, `huggingface_hub`): a read-only HTTP API and a
  Hugging Face sync CLI on top of the existing generator/probe library.
- **Storage layer** (`helpmate_server.storage`): `LocalDir` (one on-disk
  tables directory), `RemoteSource` (a Hugging Face dataset repo with a local
  download cache, size-checked catalog entries, background fetch with
  `absent`/`fetching`/`cached`/`failed` state tracking, sha256-verified
  downloads), and `ChainSource` (searches local dirs in order, then falls
  back to the remote).
- **`helpmate-server` CLI**: serves `/v1/*` routes over one or more
  `--tables` directories plus an optional `--hf-repo`/`--cache` remote;
  `--host`/`--port` (default `127.0.0.1:8642`), `--mine-cap`/`--mine-timeout`
  bound the cost of `/v1/mine` queries.
- **API routes**: `GET /v1/health`, `/v1/materials` (catalog),
  `/v1/materials/{name}/stats`, `/v1/probe` (JSON `dtm`/`count`/`flipped`/
  `notation`, or `{"solvable": false}`), `/v1/line` (`?all=true` for every
  optimal line), `/v1/mine` (dtm/count-filtered FEN scan, capped and
  timed out server-side). All errors share one envelope,
  `{"error": {"code", "message", "hint"}}`, including framework-generated
  404/405s and uncaught exceptions.
- **202-fetching semantics**: a query against a material that exists only in
  the remote manifest triggers a background download and returns
  `202 {"status": "fetching", ...}` until it completes (then `200`) or fails
  (`502 fetch_failed`); a material in neither local dirs nor the remote
  manifest is a plain `404 unknown_material`.
- **`helpmate-tables push`/`pull`** CLI: pushes a scoped or full set of
  `.hm`/`.stats.json` files to a Hugging Face dataset repo, merging into
  (never discarding entries from) any existing remote `manifest.json`; pull
  defaults to every material advertised in the remote manifest when
  `--material` is omitted, and sha256-verifies each downloaded file before
  accepting it. Exit codes: `0` success, `1` failure after starting
  (network/verification error), `2` bad usage.
- **`tests/server`**: 51 tests covering storage (local/remote/chain), the
  manifest builder/writer/verifier, every API route (catalog, probe, mine,
  202-fetching), the CLI, and package metadata; wired into CI alongside
  `tests/python`.

### Fixed

Hardening rounds found and closed during development, before any release:

- A failed remote download no longer leaves the material stuck at
  `502 fetch_failed` until server restart: the request that observes the
  failure re-triggers the download, so the client's retry sees `202` and
  then `200` — matching the hint text's promise.
- `verify_file` now correctly returns `False` (not a crash) for a file the
  manifest lists but that is missing on disk.
- The remote fetch state machine was hardened against re-fetching an
  already-cached slice, left cleaning up both `.hm` and `.stats.json` on any
  failure, and made to size-check cached files against the manifest before
  trusting them.
- Framework-generated 404/405 responses now carry the same
  `{"error": {...}}` envelope as application errors, instead of Starlette's
  bare `{"detail": ...}`.
- Empty/whitespace FENs are rejected with `400 invalid_fen` instead of
  falling through to a confusing 500 or 404.
- `push` now fails loudly (exit 1, nothing uploaded) if fetching the
  existing remote manifest errors, rather than silently uploading a
  manifest that forgets previously-pushed materials; `fetch_manifest`
  returning `None` is the explicit, documented "remote has no manifest yet"
  contract (as opposed to a fetch error).
- `pull` now defaults to every material in the remote manifest when
  `--material` is omitted, and reports errors (missing manifest, download
  failure, sha256 mismatch) without leaking a Python traceback to stderr.

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
