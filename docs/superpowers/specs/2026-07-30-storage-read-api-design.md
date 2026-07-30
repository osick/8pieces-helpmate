# Storage + Read-Only API (v0.6) — Design

Date: 2026-07-30
Status: approved by user (brainstorming session 2026-07-30)
Origin: specs/specround_2026_07_29.md ("api" + "data storage" items); first rung of docs/ROADMAP.md

## Goal

A read-only HTTP API serving helpmate tablebase queries (probe, lines, mining,
stats) to the future web dashboard and to remote CLI clients, plus a storage
layer that keeps tablebase files not only on the local machine. Writes to
storage happen only through CLI tooling, never through the API.

## Decisions (from the brainstorming session)

- **Scope v0.6:** probe (FEN → dtm/count/lines/h#), mining (dtm/count filters),
  stats/metadata/catalog. Pattern/theme search is **out of scope** — it needs a
  precomputed index and is designed with the v0.7 dashboard.
- **Deployment:** starts on the local Linux box (home network); the design must
  be public-ready (same service + object storage movable to a VPS later without
  rework). No auth in v0.6; CORS enabled for the future dashboard.
- **Off-site storage:** Hugging Face dataset repository (free, public, built
  for 100+ GB data, HTTP range reads). Other backends (S3-compatible B2/R2)
  fit behind the same abstraction later.
- **Architecture:** Python FastAPI wrapping the existing pybind11 `helpmate`
  package (option A). No C++ core changes. Probe latency is table-read-bound,
  so a C++ HTTP service (option B) buys nothing at this scale; a serverless
  smart-client design (option C) was rejected because mining over HTTP range
  reads is impractical and probe logic would be duplicated per client.

## Components

### 1. `helpmate_server` (new Python package, optional extra)

- Installed via `pip install .[server]`; adds FastAPI, uvicorn, huggingface_hub.
- Console entry point `helpmate-server` (flags: `--tables DIR ...` repeatable,
  `--hf-repo USER/DATASET`, `--cache DIR`, `--host`, `--port`, `--mine-cap N`,
  `--mine-timeout SECS`).
- Read-only: no POST/PUT/DELETE routes exist.

### 2. API surface (all under `/v1`, JSON)

| Route | Returns |
|---|---|
| `GET /v1/health` | `{status, version, tables_local, tables_remote}` |
| `GET /v1/materials` | catalog: name, piece count, max_dtm, cells, file size, location (local / remote / cached) |
| `GET /v1/materials/{name}/stats` | the slice's full stats.json (incl. dtm_histogram, uniqueness; `deepest*` fields are 5-FEN samples, as documented in USAGE.md) |
| `GET /v1/probe?fen=` | dtm, count, h# notation, flipped flag |
| `GET /v1/line?fen=&all=` | optimal line(s) in SAN |
| `GET /v1/mine?material=&dtm=&count=&max=` | mined FENs; `max` clamped to server cap |

### 3. Storage layer (`helpmate_server/storage.py`)

- `TableSource` protocol: `catalog() -> [SliceInfo]`, `resolve(material) -> Path | None`.
- Backends:
  - `LocalDir(path)` — existing tables directories.
  - `HFDataset(repo_id, cache_dir)` — lists the dataset, downloads `.hm` +
    `.stats.json` on first access into `cache_dir` (then behaves like local).
- A `ChainSource` queries local dirs first, then remote; the probe layer only
  ever sees local paths (the existing `helpmate.Tablebase` API is unchanged).
- Integrity: manifest checks (sha256) on download; the C++ loader's own
  identity checks (material name + plane size, added in the bug-21 review
  round) are the second line of defense.

### 4. Sync tooling (`helpmate-tables`, part of the same extra)

- `helpmate-tables push --tables DIR --repo USER/DATASET [--material X ...]`
  uploads `.hm` + `.stats.json` + updates `manifest.json` (per-file sha256,
  size, generator_version, upload date).
- `helpmate-tables pull --repo ... --material X --tables DIR` — explicit
  download without running the server.
- This is the only write path to remote storage ("write data via cli").

## Data flow

client → FastAPI route → validate input → `ChainSource.resolve(material)`
(local hit, or HF download-to-cache) → `helpmate.Tablebase(dir).probe/line/
lines/mine/stats` (C++ core via bindings) → JSON response.

Mining runs in a worker thread with the row cap and timeout; probe/line/stats
are effectively instant once a table is local (mmap-backed).

## Error handling

- Material unknown everywhere (not local, not in the remote catalog) → **404**
  with a hint body: the `helpmate gen` command that would build it.
- Material known remotely but not yet cached → the request **triggers a
  background download and returns 202** `{"status": "fetching", "material",
  "size_bytes"}`; clients poll/retry until the fetch completes (6-piece files
  are ~27 GB — requests must never block on a download). Subsequent requests
  while fetching return the same 202 with progress if available.
- Invalid FEN / bad parameters → **400** with the same message text the CLI
  prints (exit-code-3 class errors).
- Mining cap/timeout hit → **200** with `truncated: true` and the rows so far.
- Internal/table-corruption errors (typed GeneratorLookupError etc.) → **500**
  with the diagnostic string (they carry material+FEN+cell context by design).
- All errors: `{"error": {"code", "message", "hint?"}}`.

## Testing

- pytest + FastAPI TestClient, in `tests/server/`.
- Fixture generates the KQvk closure into a temp dir (sub-second) → golden
  assertions: probe dtm=2/count=4 position, line "Kh6 Qh2#", stats max_dtm,
  mine bounds, 404/400 paths, mine truncation.
- Storage tests: ChainSource resolution order; HF backend faked by a local
  directory fixture implementing the same interface (no network in CI);
  manifest sha256 verification (corrupt a byte → download rejected).
- CI: the existing python job gains `pip install .[server]` + these tests.
- Manual acceptance: serve the real ~/myhelpmate tables locally; probe a
  5-piece position from a browser; `helpmate-tables push` the 3-5-piece set
  to the HF dataset; delete a local slice, probe it again (fetched from HF).

## Out of scope (v0.6)

Pattern/theme search and its index (v0.7); auth/rate limiting (first public
deployment); S3-compatible backends (the abstraction allows them); serving
7-piece tables (v0.8+); any write route on the API.
