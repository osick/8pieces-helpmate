# Web dashboard (v0.7) — Design

Date: 2026-07-31
Status: approved by user (brainstorming session 2026-07-31)
Origin: `specs/specround_2026_07_29.md` ("web dashboard"), roadmap rung v0.7.
Reference studied: <https://syzygy-tables.info/> — its interactive board, the
per-move evaluation list, and position-in-the-URL sharing are the parts worth
borrowing. This is not a copy: the domain (helpmates, DTM + optimal-line
counts, composition search) differs.

## Scope decision

The roadmap's v0.7 bundled four independent subsystems. Decomposed:

- **v0.7 (this spec): the dashboard MVP** — a browser client of the existing
  read-only API, plus the one API addition it genuinely needs.
- **v0.8: pattern/theme search** — needs a theme taxonomy, a precomputed
  index, generation tooling and new endpoints. Its own spec.
- **Independent, unscheduled: cross-platform builds** (Windows/macOS/WSL CI
  matrix) — unrelated to the UI.

## Architecture

Static files (`web/`), mounted by the existing FastAPI app at `/`. One
process, one port: `helpmate-server --tables ~/tb` serves the API *and* the
UI. No npm, no bundler, no build step — plain HTML/CSS and ES modules that
browsers load directly. Works offline. The dashboard is a pure API client;
storage and generation are untouched.

Third-party code is vendored, never fetched at runtime: **cm-chessboard**
(MIT, dependency-free ES module, piece SVGs included) is committed under
`web/vendor/cm-chessboard/` at a pinned version, with its LICENSE and the
upstream version recorded in `web/vendor/README.md`.

## The one backend addition: `GET /v1/moves`

The per-move evaluation list cannot be built from today's API: `_legal_moves`
returns UCI strings with no SAN, no resulting position and no value, so a
browser would need its own move generator plus ~40 probe calls per position.

`GET /v1/moves?fen=<FEN>` returns the position's own value and every legal
move in one call:

```json
{
  "fen": "8/7k/5K2/8/8/8/8/6Q1 b - - 0 1",
  "dtm": 2, "count": 4, "notation": "h#1", "flipped": false,
  "moves": [
    {"uci": "h7h6", "san": "Kh6", "fen": "<after>", "dtm": 1, "count": 3,
     "notation": "h#0.5", "optimal": true},
    {"uci": "h7h8", "san": "Kh8", "fen": "<after>", "dtm": 1, "count": 1,
     "notation": "h#0.5", "optimal": true}
  ]
}
```

- `optimal` is true when the move leads to `dtm - 1`, i.e. it keeps the
  shortest mate. The client highlights those.
- A move leading to a position with no table, or an unsolvable one, carries
  `"dtm": null, "solvable": false` and `optimal: false` — displayed as "no
  table"/"unsolvable" rather than omitted, so the move list is always the
  complete legal-move list.
- Unsolvable *query* position → `{"solvable": false, "moves": [...]}` with the
  moves still enumerated (a composer may want to walk into a solvable branch).
- Invalid FEN → 400 `invalid_fen`; unknown material → 404 with the
  `helpmate gen …` hint; remote-only material → the existing 202 fetching
  contract. All through the established error envelope.

Implementation: a `Tablebase::moves(fen)` method in the probe library (it
already owns legal-move generation via `Board`, SAN formatting, table lookup
and the color-flip fallback), bound to Python and exposed by the route. No
new logic in the server layer beyond validation and serialization.

## Screens

**Explorer** (the centre). An interactive board: drag pieces to edit, a piece
palette for adding/removing, flip, clear, and a FEN box for paste/copy. Shows
the position's dtm, optimal-line count and h# notation; the complete legal-move
list with each move's resulting value, optimal moves highlighted; click a move
to play it forward, with back/undo; and the optimal lines in SAN. The position
is encoded in the URL (`/#fen=<urlencoded>`), so every position is a shareable
link and browser back/forward navigates history.

**Material browser.** Renders `/v1/materials`: name, piece count, size,
location (local/cached/remote), max_dtm. Selecting one shows its stats from
`/v1/materials/{name}/stats` — dtm histogram, uniqueness histogram, deepest
and deepest-unique sample positions — each sample clickable into the explorer.

**Mine / composition search.** A form over `/v1/mine`: material, dtm, count,
and the v0.6.2 `starts`/`ends` filters, plus max. Results are a clickable FEN
list opening in the explorer. `skipped_saturated` is displayed when non-zero.
Client-side validation mirrors the API's rules so obvious mistakes are caught
before the request, but the server remains the authority.

**Export** (client-side only, no endpoint): the current mine result set as a
FEN list or CSV; the current position's optimal lines as PGN; download via a
Blob URL.

## Error and loading behaviour

Every API contract the server already defines is surfaced honestly rather than
rendered as breakage: `202 fetching` shows "downloading <material>
(<size>)…" and polls until it resolves; `404` shows the returned `helpmate
gen …` hint; `400` shows the message inline next to the offending field;
`502 fetch_failed` explains that the download failed and that retrying
re-triggers it; a `500` shows the diagnostic text (these carry
material/FEN/cell context by design).

## Testing

- **API**: pytest over `/v1/moves` against a real generated `KQvk` closure —
  golden values for the golden position (dtm 2, count 4, two optimal moves
  `Kh6`/`Kh8`, complete legal-move list), the unsolvable and dtm-0 cases, an
  invalid FEN (400), an unknown material (404), and that `optimal` is exactly
  the set of moves reaching `dtm - 1`.
- **C++**: `Tablebase::moves` unit tests alongside the existing probe tests,
  including the color-flip case and a position whose moves cross into another
  material by capture.
- **JS**: pure helpers (URL state encode/decode, PGN and CSV builders, FEN
  validation) live in `web/js/lib/*.js` with no DOM dependency and are tested
  with Node's built-in test runner (`node --test`).
- **Browser (end-to-end)**: pytest + Playwright, driving headless Chromium
  against a live `helpmate-server` fixture with a generated `KQvk` closure.
  Playwright was verified working on the development machine on 2026-07-31 —
  no shared libraries are missing; it needs `--no-sandbox` because user
  namespaces are restricted, and the driver package (`pip install playwright`)
  was the only thing that had ever been absent. The cases that matter are
  exactly the ones a manual checklist forgets:
  - loading `/` renders the board and the initial position;
  - dragging a piece updates the FEN box and re-queries the position;
  - clicking a legal move advances the board, updates the move list, and
    pushes a new URL; the browser's back button restores the previous position;
  - opening a shared `#fen=` link restores that exact position;
  - the mine form rejects an invalid filter combination inline and shows the
    server's message for one it cannot catch;
  - a material that is remote-only shows the fetching state rather than an
    error.
  These run as their own CI job (`ui`), with the Playwright browser download
  cached between runs. A broken dashboard fails the build like any other
  regression.

## CI

The existing `ci.yml` gains a `ui` job: install `.[dev,server]` plus
`playwright`, `python -m playwright install --with-deps chromium` (cached via
`actions/cache` on `~/.cache/ms-playwright`), generate a small `KQvk` closure,
start `helpmate-server`, and run the browser suite. The `node --test` helper
tests run in the same job — Node is already present on GitHub runners, so no
extra setup. Existing jobs are unchanged.

## Out of scope

Pattern/theme search and its index (v0.8); authentication and rate limiting
(first public deployment); any write path — the API stays read-only, tables
are still produced by the CLI; mobile-first layout beyond basic
responsiveness; i18n.
