# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
version numbers follow [Semantic Versioning](https://semver.org/) (0.x: minor
bumps may change behavior).

## [Unreleased]

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
- **`tests/server`**: 47 tests covering storage (local/remote/chain), the
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
