# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
version numbers follow [Semantic Versioning](https://semver.org/) (0.x: minor
bumps may change behavior).

## [0.7.5] - 2026-08-02

### Added

- **Block-compressed tables** (`version 3`, `encoding 2`): the four planes are
  addressed as one logical byte range, cut into fixed-size blocks compressed
  independently with zstd, with a `uint64` offset index and a bounded cache of
  decompressed blocks. Random access is preserved — a probe decompresses one
  block. Measured 14.5× on a 128 MB sample of a real 6-piece plane at 64
  KB/level 3. Realized whole-table numbers vary with table size and block
  size: a real 5-piece table (`KBvkbn`) went from 462 MiB to 50 MiB end to end
  (9.22×) at 64 KB, while a 146 KB `KQvk` only reaches 2.0× — small tables
  compress poorly because fixed per-file overhead (header, JSON, a block
  index covering just a couple of blocks) dominates a file too small to give
  zstd much to work with.
- **`helpmate gen --compress`** and **`helpmate compact --compress`**. The
  converter rewrites tables already on disk one at a time via a temp file and
  atomic rename, and skips markers, already-compressed tables, and anything
  written in the last hour, so a running generation is never disturbed.
- **libzstd** is now a build prerequisite (`libzstd-devel` on openSUSE,
  `libzstd-dev` on Debian/Ubuntu).
- **`--block-size N`** on `gen --compress` and `compact --compress` (KiB;
  4-16384, i.e. 4 KiB-16 MiB). Real-world use found `helpmate mine
  --count`/`--starts` — which probes child positions effectively at random —
  5× slower on a 64 KB-block compressed table than raw, so the default
  (`kDefaultBlockSize`) is now **16 KiB**, down from 64 KiB. Reproducing the
  regression on a real 462 MiB `KRvkbn` table measured raw 0.05s vs. ~0.32s
  compressed at *both* 64 KiB and 16 KiB (~6.5×, no measurable improvement
  from the smaller default in this reproduction — see docs/USAGE.md's Table
  format section for the full numbers and an open question about why, plus
  the isolated per-block-miss measurements, 16 KiB/level 3 = 11.4×/~11µs vs.
  64 KiB/level 3 = 14.5×/~38µs, that motivated trying it).
- **`compact --compress` can now re-block an already-compressed table** to a
  different `--block-size` in place, streaming through the reader's own
  bounded block cache rather than a decompress-to-disk round trip or
  regenerating from scratch (`TableReader::read_range`, works for raw and
  compressed sources alike). At the same block size it stays a true no-op.
  Verified byte-identical to a direct raw→target-size compression (`md5sum`
  match on a real table).
- `helpmate.generate()` (Python bindings) gained `compress` and `block_size`
  keyword arguments, matching the CLI's `--compress`/`--block-size` (in raw
  bytes, not KiB — see docs/USAGE.md's Python API reference).

### Changed

- Raw tables remain the default for `gen`. The default flips in a later
  version, once the performance gate has been run at scale.
- Compressed tables carry `version = 3` as well as `encoding = 2`, so binaries
  released before this format report "written by a newer helpmate … upgrade
  this build" rather than "unreadable table".
- The default block size for `gen --compress`/`compact --compress` is now 16
  KiB (was 64 KiB); the golden fixture committed at 64 KiB is unaffected —
  block size is read from each file's own header, not the build's default.

## [0.7.2] - 2026-08-01

### Added

- **Every pull request is gated.** `ruff`, `mypy`, `node --check`,
  `clang-format` on changed lines, and the full C++/Python/browser suites run
  on each PR, and `main` requires them to pass before a merge is allowed.
- **`make lint`, `make typecheck`, `make format-check`** reproduce every gate
  locally; `make format` fixes the C++ ones.
- **The release workflow verifies that a pushed `v*` tag matches `VERSION`**,
  closing the last place the version could drift unguarded.
- **`docs/CONTRIBUTING.md`** — the required checks, how to run each locally,
  and the reasoning behind the linter configuration.

### Changed

- Ruff's E701/E702/E401 are disabled project-wide, with the reasoning
  recorded: all 55 findings under them are deliberate paired statements and
  combined imports, not defects. Every other default rule is enabled and
  passes on the whole tree, with no grandfathered violations.
- C++ formatting is enforced on changed lines only. A stock style would
  rewrite 3715 lines of the 4365-line core; the tuned config still 971. The
  tree converges as it is edited rather than in one unreviewable commit.

### Fixed

- **`ctest` could pass while testing a stale binary.** The v0.7.1 CMake split
  moved the built executables into subdirectories. `ctest` resolves target
  paths itself, so it kept passing, but a pre-split build had left stale
  binaries at the old top-level paths, and `./build/helpmate_tests
  "~[slow]"` kept answering — from a binary built before the change it was
  meant to verify. Five tasks' worth of that gate were therefore meaningless.
  Fixed in v0.7.1 by `CMAKE_RUNTIME_OUTPUT_DIRECTORY`; this release adds the
  CI step that asserts the binaries exist at their documented paths, so a
  future layout change fails loudly in one place instead of silently
  everywhere.
- **`make format-check` reported success whenever it could not run.**
  `git clang-format` writes errors to stderr, `tee` captured only stdout, and
  with no `pipefail` the recipe's exit status was `tee`'s — always 0. An
  unresolvable base ref, a missing `clang-format`, or an unwritable temp path
  all produced a green check. On a shallow CI checkout this would have made
  the formatting gate a permanent no-op. Every condition that prevents the
  check from running now exits non-zero.
- **`node --check` does not validate ES modules.** Node's CommonJS-first
  auto-detection short-circuits at the first `import`/`export`, so any syntax
  error after that line was silently accepted. Every dashboard module has an
  import within its first nine lines, so the JS gate was validating almost
  nothing. Each file is now checked through a temporary `.mjs` copy, which
  forces unambiguous ESM parsing.
- Four unused imports, two ambiguous `l` variable names, one lambda bound to
  a name, and two mypy findings — one of which was a `# type: ignore` naming
  the wrong error code, so it had been silencing nothing.

## [0.7.1] - 2026-08-01

### Changed

- **The repo is now three separately installable distributions.**
  `helpmate` (C++ core, the `helpmate` CLI binary, and the Python bindings),
  `helpmate-api` (the FastAPI service and `helpmate-tables`), and
  `helpmate-web` (the dashboard). Each has its own `pyproject.toml` or
  `CMakeLists.txt` and owns its own test suite under
  `src/packages/<name>/tests/`. `make install` installs all three in
  dependency order.
- **`pip install helpmate` now puts the `helpmate` command on PATH.** The
  wheel carries the compiled binary, so using the CLI no longer requires a
  C++ toolchain on the target machine.
- **The API locates the dashboard by importing `helpmate_web`**, with
  `--web-root DIR` to override and `--no-web` to serve the API alone. The
  previous version guessed between two filesystem layouts and served nothing
  when it guessed wrong.
- **One `VERSION` file** feeds CMake, `version.h` and the `cli_version` test
  regex; a repo-level test asserts the three `pyproject.toml` literals,
  `helpmate.__version__`, `helpmate_server.__version__` and
  `helpmate --version` all agree with it.

### Migration

`pip install ".[server]"` no longer exists — the server is a different
distribution. Use `make install`, or
`pip install . ./src/packages/api ./src/packages/web` **in that order**
(`helpmate-api` requires `helpmate`, and nothing is published to PyPI yet).

## [0.7.0] - 2026-08-01

### Added

- **Web dashboard**: `helpmate-server` now also serves a static single-page
  dashboard at `/` (mounted after every `/v1` route, so the API is never
  shadowed) — no separate process or build step, just
  `helpmate-server --tables <dir>` and open `http://127.0.0.1:8642/`.
  - **Explorer** panel: an interactive board (drag a piece to play a legal
    move, with a promotion dialog when needed) showing the position's
    dtm/count/h#n and every optimal move, click a move to advance and push
    history, `Back` to undo, `Flip` to change orientation, a FEN box to jump
    to any position, and a "Download PGN" export of the current line. The
    current position lives in the URL (`#fen=...`), so any explorer view is
    a shareable link that opens directly to that position in a fresh tab.
  - **Position editor**: a piece palette under the board places pieces by
    clicking squares, with `Erase`, `Clear board` and a `To move` selector.
    Editing deliberately does not probe on every click — a half-built
    position is illegal by definition — so the value appears when the
    editing session ends. A position with no king, or two of one colour, is
    reported directly instead of spending a request to be told
    `invalid_fen`.
  - **Materials** panel: browse every catalogued material class and its
    generation-time stats — where the cells went (solvable / no mate /
    illegal), a mate-length histogram split by side to move, a histogram of
    how many distinct optimal solutions positions have (exact for 1–4, then
    bucketed by octave, with the saturated 255+ bucket called out), and the
    deepest and deepest-unique sample positions, each clickable into the
    explorer.
  - **Search** panel: the `mine` scan (material, dtm, optional
    count/starts/ends/max) with truncation and skipped-saturated reporting,
    plus "Download FENs" (plain text) and "Download CSV" exports of the
    result set.
  - No CDN dependencies: the board library (`cm-chessboard`) is vendored
    under `web/vendor/`, so the dashboard works fully offline.
- **`GET /v1/moves`**: given a `fen`, returns the position's own
  dtm/count/notation/flipped (or `solvable: false`) plus every legal move
  annotated with its resulting FEN, dtm, count, notation, and whether it is
  one of the optimal moves — the data the explorer's move list and
  click-to-advance are built on. See
  [USAGE.md](docs/USAGE.md#get-v1moves) for the response shape and a real
  captured example.
- **Browser test suite** (`tests/ui/`, Playwright + headless Chromium): 11
  end-to-end tests driving a real `helpmate-server` process against a
  freshly generated `KQvk` closure — the golden position's dtm/count/move
  count, click-to-advance plus `Back`, a `#fen=` link opening the exact
  position in a fresh tab, panel exclusivity, both stats histograms and
  their agreement with the cell tiles, a full palette editing session, the
  missing-kings report, the server chip, and the mine panel's
  truncation/validation behavior. Wired into CI as a new `ui` job (installs
  the `dev`+`server` extras, caches and installs headless Chromium, runs the
  pure-JS helper tests and the Playwright suite).
- **Pure JS helpers** (`web/js/lib/`) covered by `node --test
  tests/js/*.test.js` (`make jstest`), independent of the browser suite: URL
  state encode/decode, FEN/PGN/CSV export formatting, FEN composition and
  king validation for the editor, and the histogram/cell-summary shaping the
  materials panel draws.

### Fixed

- **Every dashboard panel rendered at once**: `#panel-explorer { display:
  flex }` is an id selector and outranks the user-agent `[hidden]` rule, so
  hiding a panel did nothing and the three screens stacked. `[hidden] {
  display: none !important }` restores the intent; a browser test now
  asserts panel exclusivity, which the previous suite could not catch
  because it only checked that elements inside the target panel were
  visible.
- **`Tablebase::moves` threw on a king capture**: a capture of the king is
  a "legal move" only from an already illegal position (the side not to move
  is in check) — reachable from the new position editor — and probing the
  resulting position raised `invalid_argument`, so a whole `/v1/moves`
  request failed with an `invalid_fen` naming a FEN the caller never sent,
  while `/v1/probe` answered the same input fine. Such a move is now
  reported as having no value, like a move into a material with no table,
  and the move list stays complete.
- **`wheel.packages` didn't ship `web/`**: a non-editable `pip install`
  built a server with no dashboard to serve. `web/` is now included in
  `[tool.scikit-build] wheel.packages`, and `create_app`'s static-mount
  lookup checks both the installed-wheel layout (`web/` as a sibling
  package of `helpmate_server` in `site-packages`) and the source-checkout
  layout (`web/` at the repo root), so the dashboard is served either way.
- **`tests/ui/conftest.py` server fixture hardening**: the env dict literal
  used to let a pre-existing `HELPMATE_TABLES` in the environment silently
  win over the freshly generated scratch tables dir; a stuck server on
  teardown could raise `TimeoutExpired` and leak an orphan process holding
  the port; and a startup crash was swallowed by `DEVNULL`, surfacing only
  as a generic "server did not start" after the poll timeout. All three
  fixed: the scratch tables dir always wins, teardown falls back to `kill()`
  on a timeout, and captured subprocess output is included in the startup
  error so a CI failure is diagnosable.

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
