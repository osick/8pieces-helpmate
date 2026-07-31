# Web dashboard (v0.7) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** a browser dashboard — position explorer with an interactive board, material browser, mining/composition search and export — served by the existing API process; spec: `docs/superpowers/specs/2026-07-31-web-dashboard-design.md`.

**Architecture:** Static files under `web/`, mounted by the existing FastAPI app at `/`; no npm, no bundler, no build step. The dashboard is a pure client of the read-only API plus one addition, `GET /v1/moves`, which returns every legal move with the value it leads to (built on a new `Tablebase::moves`). Pure JS helpers live in dependency-free modules tested under Node; DOM behaviour is covered by Playwright against a live server.

**Tech Stack:** C++20 (GCC 13) + pybind11 for the new probe method; FastAPI + pytest for the route and static mount; vanilla ES modules + vendored cm-chessboard for the UI; `node --test` for JS helpers; Playwright (Python, headless Chromium) for browser tests.

## Global Constraints

- **The dashboard is a pure API client.** No new logic in the UI that belongs in the API, and no write paths — the API stays read-only.
- **No build step.** Plain HTML/CSS and ES modules loaded directly by the browser. No npm dependency for the shipped dashboard (Node is used only to *run tests*).
- **Vendored, never fetched at runtime:** cm-chessboard is committed under `web/vendor/cm-chessboard/` at a pinned version, with its LICENSE and the upstream version recorded in `web/vendor/README.md`.
- **Verified goldens (measured, do not re-derive):** the KQvk position `8/7k/5K2/8/8/8/8/6Q1 b - - 0 1` has dtm 2, count 4, notation `h#1`, and exactly two optimal first moves `Kh6` and `Kh8`; its four optimal lines are `Kh6 Qh2#`, `Kh6 Qh1#`, `Kh6 Qg6#`, `Kh8 Qg7#`. `mine` emits CANONICAL FENs — the same position's canonical form is `8/8/8/8/8/2K5/7Q/1k6 b - - 0 1` (starts 2, ends 4); use the canonical form for any assertion about `mine` output, either form for probe/line/moves.
- **Error contracts already defined by the API must be surfaced, not hidden:** 202 fetching (poll), 404 with the `helpmate gen …` hint, 400 inline, 502 `fetch_failed`, 500 diagnostic text.
- Build: `PATH="$HOME/.local/bin:$PATH"`, `cmake --build build -j4`; never let CMake FetchContent clone from GitHub (SSH passphrase). FAST SUITE = `taskset -c 0-3 ./build/helpmate_tests "~[slow]"` — **never** the bare invocation (it adds a 30-60 minute `[slow]` lane). ctest: `cd build && taskset -c 0-3 ctest --output-on-failure`.
- Python/C++ binding changes require a reinstall to test:
  `PATH="$HOME/.local/bin:$PATH" CXX=/usr/bin/g++-13 CC=/usr/bin/gcc-13 SKBUILD_CMAKE_ARGS="-DFETCHCONTENT_FULLY_DISCONNECTED=ON;-DFETCHCONTENT_SOURCE_DIR_CHESSMG=$PWD/build/_deps/chessmg-src;-DFETCHCONTENT_SOURCE_DIR_CATCH2=$PWD/build/_deps/catch2-src;-DFETCHCONTENT_SOURCE_DIR_JSON=$PWD/build/_deps/json-src" pip install -e ".[dev,server]"`
- **Playwright on this machine:** works, but launch headless Chromium with `args=["--no-sandbox"]` (user namespaces are restricted here). The driver is installed; browsers live in `~/.cache/ms-playwright`.
- **Never touch `~/tb`** — a multi-day 6-piece generation writes there. Use scratch directories.
- Commits are local (never push); message ends with the trailer line exactly: `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.

## File structure

```
src/probe/tablebase.{h,cpp}      MoveInfo + Tablebase::moves           (Task 1)
src/bindings/pymodule.cpp        moves binding                          (Task 2)
server/helpmate_server/app.py    GET /v1/moves, static mount            (Tasks 2, 3)
web/index.html                   shell: header, nav, three panels       (Task 3)
web/css/app.css                  layout and board styling               (Task 3)
web/js/lib/state.js              URL <-> position state (pure)          (Task 4)
web/js/lib/export.js             PGN / CSV / FEN-list builders (pure)   (Task 4)
web/js/api.js                    fetch wrappers + error/202 handling    (Task 5)
web/js/explorer.js               board, move list, lines                (Task 6)
web/js/materials.js              catalog + stats views                  (Task 7)
web/js/mine.js                   search form, results, export buttons   (Task 7)
web/vendor/cm-chessboard/        vendored board library + LICENSE       (Task 6)
tests/js/*.test.js               node --test for the pure helpers       (Task 4)
tests/ui/test_dashboard.py       Playwright end-to-end                  (Task 8)
.github/workflows/ci.yml         new `ui` job                           (Task 9)
```

---

### Task 1: `Tablebase::moves`

**Files:**
- Modify: `src/probe/tablebase.h` (struct + declaration next to `lines`), `src/probe/tablebase.cpp`
- Test: `tests/cpp/test_probe.cpp` (append)

**Interfaces:**
- Consumes: `Board::from_fen/legal_moves/make/unmake/fen` (`src/chess/board.h:14-28`), `san(Board&, const Move&)` (`src/chess/san.h:10`), `Tablebase::probe`.
- Produces:
  ```cpp
  struct MoveInfo {
      std::string uci;      // "h7h6"
      std::string san;      // "Kh6"
      std::string fen;      // position after the move
      int  dtm      = -1;   // -1 when the child is unsolvable or has no table
      int  count    = 0;
      bool solvable = false;
      bool optimal  = false; // child dtm == parent dtm - 1
  };
  std::vector<MoveInfo> Tablebase::moves(const std::string& fen) const;
  ```
  Throws `std::invalid_argument` on an unparseable FEN (same as `probe`). A child position whose table is missing yields `solvable=false, dtm=-1` rather than propagating `MissingTableError` — the move list must always be complete.

- [ ] **Step 1: Write the failing test**

Append to `tests/cpp/test_probe.cpp` (it already has the shared `gen_dir()` fixture at line 8, which generates `KQvk` and `KPvk` once per run — use it):

```cpp
TEST_CASE("moves lists every legal move with the value it leads to") {
    Tablebase tb(gen_dir());
    auto ms = tb.moves("8/7k/5K2/8/8/8/8/6Q1 b - - 0 1");

    // Black king on h7, White king f6 covers g6/g7/h6... the black king's legal
    // moves are exactly Kh6 and Kh8 (g8 is covered by nothing, but g7/g6 are).
    std::set<std::string> sans;
    for (const auto& m : ms) sans.insert(m.san);
    CHECK(sans.count("Kh6") == 1);
    CHECK(sans.count("Kh8") == 1);

    // Both are optimal (they lead to dtm 1 from this dtm-2 position).
    for (const auto& m : ms) {
        INFO("move " << m.san);
        if (m.san == "Kh6" || m.san == "Kh8") {
            CHECK(m.optimal);
            CHECK(m.solvable);
            CHECK(m.dtm == 1);
        } else {
            CHECK_FALSE(m.optimal);
        }
        // every entry carries a usable resulting position
        auto after = Board::from_fen(m.fen);
        CHECK(after.has_value());
        CHECK_FALSE(m.uci.empty());
    }
    // the number of optimal moves matches the distinct first moves of the
    // optimal lines (Kh6, Kh8) -- see the golden lines in the plan header
    int opt = 0;
    for (const auto& m : ms) if (m.optimal) ++opt;
    CHECK(opt == 2);
}

TEST_CASE("moves reports unsolvable children instead of hiding them") {
    Tablebase tb(gen_dir());
    // dtm-0 position: Black is already mated, so there are no legal moves.
    CHECK(tb.moves("8/8/8/8/8/8/8/kQK5 b - - 0 1").empty());
    // A position where a capture leads into Kvk (unsolvable): the move must be
    // listed with solvable=false rather than dropped or throwing.
    auto ms = tb.moves("8/7k/8/8/8/8/8/6QK b - - 0 1");
    bool saw_capture = false;
    for (const auto& m : ms)
        if (m.san.find('x') != std::string::npos) { saw_capture = true; CHECK_FALSE(m.optimal); }
    INFO("this FEN must offer at least one capture for the test to mean anything");
    CHECK(saw_capture);
}

TEST_CASE("moves rejects a bad FEN like probe does") {
    Tablebase tb(gen_dir());
    CHECK_THROWS_AS(tb.moves("garbage"), std::invalid_argument);
}
```

**Note to implementer:** the second test's FEN must genuinely allow a capture of the queen by the black king. Verify with `./build/helpmate probe` / a scratch program before relying on it; if `8/7k/8/8/8/8/8/6QK b - - 0 1` has no capture (kings adjacent to the queen matter), pick one that does — e.g. place the black king next to the white queen with the white king defending nothing — and record the FEN you used in your report. Do not weaken the assertion; fix the fixture.

- [ ] **Step 2: Run it**

`PATH="$HOME/.local/bin:$PATH" cmake --build build -j4` → FAILS: `'moves' is not a member of 'hm::Tablebase'`.

- [ ] **Step 3: Implement**

`src/probe/tablebase.h`, next to the `lines` declaration:

```cpp
// One legal move from a queried position, with the value of the position it
// leads to. `dtm == -1 && !solvable` covers both "unsolvable" and "no table
// for the resulting material" -- the list is always the complete legal-move
// list, so a caller can render every option.
struct MoveInfo {
    std::string uci;
    std::string san;
    std::string fen;
    int  dtm      = -1;
    int  count    = 0;
    bool solvable = false;
    bool optimal  = false;
};
```

and in the public section:

```cpp
    // Every legal move from `fen`, each with the value of the resulting position.
    std::vector<MoveInfo> moves(const std::string& fen) const;
```

`src/probe/tablebase.cpp` (place it after `lines`):

```cpp
std::vector<MoveInfo> Tablebase::moves(const std::string& fen) const {
    auto b = Board::from_fen(fen);
    if (!b) throw std::invalid_argument("bad FEN: " + fen);
    int parent_dtm = -1;
    if (auto p = probe(fen)) parent_dtm = p->dtm;

    std::vector<MoveInfo> out;
    for (const Move& m : b->legal_moves()) {
        MoveInfo mi;
        mi.uci = m.uci();
        mi.san = san(*b, m);          // SAN must be computed BEFORE the move is made
        b->make(m);
        mi.fen = b->fen();
        b->unmake(m);
        try {
            if (auto c = probe(mi.fen)) {
                mi.dtm = c->dtm;
                mi.count = c->count;
                mi.solvable = true;
                mi.optimal = parent_dtm > 0 && c->dtm == parent_dtm - 1;
            }
        } catch (const MissingTableError&) {
            // no table for the resulting material: leave solvable=false
        }
        out.push_back(std::move(mi));
    }
    return out;
}
```

Add `#include "chess/san.h"` if absent.

- [ ] **Step 4: Run it**

```
PATH="$HOME/.local/bin:$PATH" cmake --build build -j4
taskset -c 0-3 ./build/helpmate_tests "moves *"
taskset -c 0-3 ./build/helpmate_tests "~[slow]"
```
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/probe/tablebase.h src/probe/tablebase.cpp tests/cpp/test_probe.cpp
git commit   # feat: Tablebase::moves - every legal move with the value it leads to
```

---

### Task 2: `GET /v1/moves`

**Files:**
- Modify: `src/bindings/pymodule.cpp` (add a `moves` binding next to `lines`), `server/helpmate_server/app.py` (new route after `/v1/line`)
- Test: `tests/server/test_api_moves.py` (create)

**Interfaces:**
- Consumes: `Tablebase::moves` / `MoveInfo` (Task 1); `_dir_for_fen`, `_resolve_or_response`, `error_json`, `unknown`, `h_notation`, `_tb` in `app.py` (read the `/v1/probe` route at `app.py:117-139` — mirror its material resolution and error handling exactly).
- Produces: `GET /v1/moves?fen=` returning
  ```json
  {"fen": "...", "dtm": 2, "count": 4, "notation": "h#1", "flipped": false,
   "moves": [{"uci": "h7h6", "san": "Kh6", "fen": "...", "dtm": 1, "count": 3,
              "notation": "h#0.5", "solvable": true, "optimal": true}]}
  ```
  An unsolvable query position returns `{"solvable": false, "moves": [...]}` (moves still listed). Python binding: `Tablebase.moves(fen) -> list[dict]`.

- [ ] **Step 1: Write the failing test**

Create `tests/server/test_api_moves.py` (the `client` fixture in `tests/server/conftest.py` serves a generated `KQvk` closure):

```python
GOLDEN = "8/7k/5K2/8/8/8/8/6Q1 b - - 0 1"

def test_moves_golden(client):
    r = client.get("/v1/moves", params={"fen": GOLDEN})
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["dtm"], body["count"], body["notation"]) == (2, 4, "h#1")

    by_san = {m["san"]: m for m in body["moves"]}
    assert {"Kh6", "Kh8"} <= set(by_san)
    # exactly the moves reaching dtm-1 are flagged optimal
    optimal = {m["san"] for m in body["moves"] if m["optimal"]}
    assert optimal == {"Kh6", "Kh8"}
    for san in optimal:
        assert by_san[san]["dtm"] == 1
        assert by_san[san]["solvable"] is True
        assert by_san[san]["notation"] == "h#0.5"
    # every move carries a resulting position and a uci
    for m in body["moves"]:
        assert m["fen"] and m["uci"]

def test_moves_of_a_mated_position_is_empty(client):
    r = client.get("/v1/moves", params={"fen": "8/8/8/8/8/8/8/kQK5 b - - 0 1"})
    assert r.status_code == 200
    assert r.json()["moves"] == []

def test_moves_invalid_fen_and_unknown_material(client):
    r = client.get("/v1/moves", params={"fen": "garbage"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_fen"
    r = client.get("/v1/moves", params={"fen": "1n2k3/8/8/8/8/8/8/QR2K3 b - - 0 1"})
    assert r.status_code == 404
    assert "helpmate gen" in r.json()["error"]["hint"]

def test_moves_missing_parameter(client):
    assert client.get("/v1/moves").status_code == 400
```

- [ ] **Step 2: Run it**

`taskset -c 0-3 python -m pytest tests/server/test_api_moves.py -v` → FAILS with 404 (no such route).

- [ ] **Step 3: Implement**

`src/bindings/pymodule.cpp`, next to the `lines` binding:

```cpp
        .def("moves", [](const Tablebase& t, const std::string& fen) {
            py::list out;
            for (const auto& m : t.moves(fen)) {
                py::dict d;
                d["uci"] = m.uci;  d["san"] = m.san;  d["fen"] = m.fen;
                d["dtm"] = m.solvable ? py::cast(m.dtm) : py::none();
                d["count"] = m.count;
                d["solvable"] = m.solvable;
                d["optimal"] = m.optimal;
                out.append(std::move(d));
            }
            return out;
        }, py::arg("fen"))
```

`server/helpmate_server/app.py`, after the `/v1/line` route (mirror `/v1/probe`'s resolution and error handling):

```python
    @app.get("/v1/moves")
    def moves(fen: str):
        material = None
        try:
            material = _dir_for_fen(fen)
            flipped = material.split("v")[1].upper() + "v" + material.split("v")[0].lower()
            d = chain.resolve(material) or chain.resolve(flipped)
            if d is None:
                d, resp = _resolve_or_response(material)
                if resp is not None:
                    return resp
            tb = _tb(chain, d)
            res = tb.probe(fen)
            raw = tb.moves(fen)
        except helpmate.MissingTableError:
            return unknown(material or fen)
        except ValueError as e:
            return JSONResponse(status_code=400,
                                content=error_json("invalid_fen", str(e)))
        out = []
        for m in raw:
            out.append({**m,
                        "notation": h_notation(m["dtm"]) if m["solvable"] else None})
        if res is None:
            return {"fen": fen, "solvable": False, "moves": out}
        dtm, count, flip = res
        return {"fen": fen, "dtm": dtm, "count": count, "notation": h_notation(dtm),
                "flipped": flip, "moves": out}
```

- [ ] **Step 4: Rebuild, reinstall, run**

```
PATH="$HOME/.local/bin:$PATH" cmake --build build -j4
PATH="$HOME/.local/bin:$PATH" CXX=/usr/bin/g++-13 CC=/usr/bin/gcc-13 SKBUILD_CMAKE_ARGS="-DFETCHCONTENT_FULLY_DISCONNECTED=ON;-DFETCHCONTENT_SOURCE_DIR_CHESSMG=$PWD/build/_deps/chessmg-src;-DFETCHCONTENT_SOURCE_DIR_CATCH2=$PWD/build/_deps/catch2-src;-DFETCHCONTENT_SOURCE_DIR_JSON=$PWD/build/_deps/json-src" pip install -e ".[dev,server]"
taskset -c 0-3 python -m pytest tests/python tests/server -v
```
Expected: all pass, including the four new tests.

- [ ] **Step 5: Commit**

```bash
git add src/bindings/pymodule.cpp server/helpmate_server/app.py tests/server/test_api_moves.py
git commit   # feat: GET /v1/moves - legal moves with the value each leads to
```

---

### Task 3: Static mount and page shell

**Files:**
- Create: `web/index.html`, `web/css/app.css`
- Modify: `server/helpmate_server/app.py` (mount static files LAST, after all `/v1` routes)
- Test: `tests/server/test_static.py` (create)

**Interfaces:**
- Produces: the app serves `web/index.html` at `/` and assets under `/css`, `/js`, `/vendor`. The page contains three panels with stable ids the later tasks and the browser tests target: `#panel-explorer`, `#panel-materials`, `#panel-mine`, plus `#board`, `#fen-input`, `#position-summary`, `#move-list`, `#lines`, `#material-list`, `#mine-form`, `#mine-results`, `#error-banner`.

- [ ] **Step 1: Write the failing test**

Create `tests/server/test_static.py`:

```python
def test_dashboard_is_served(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    body = r.text
    for anchor in ("id=\"board\"", "id=\"fen-input\"", "id=\"move-list\"",
                   "id=\"material-list\"", "id=\"mine-form\""):
        assert anchor in body, anchor

def test_stylesheet_is_served(client):
    r = client.get("/css/app.css")
    assert r.status_code == 200
    assert "text/css" in r.headers["content-type"]

def test_api_routes_still_win_over_static(client):
    # the static mount must not shadow /v1
    assert client.get("/v1/health").status_code == 200
```

- [ ] **Step 2: Run it**

`taskset -c 0-3 python -m pytest tests/server/test_static.py -v` → FAILS (404 for `/`).

- [ ] **Step 3: Implement**

`web/index.html` — the shell (no logic; scripts are added in later tasks):

```html
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>helpmate tablebases</title>
<link rel="stylesheet" href="/css/app.css">
</head>
<body>
<header>
  <h1>helpmate tablebases</h1>
  <nav>
    <button data-panel="explorer" class="active">Explorer</button>
    <button data-panel="materials">Materials</button>
    <button data-panel="mine">Search</button>
  </nav>
</header>

<div id="error-banner" hidden></div>

<main>
  <section id="panel-explorer">
    <div id="board"></div>
    <div class="side">
      <form id="fen-form">
        <label for="fen-input">FEN</label>
        <input id="fen-input" type="text" spellcheck="false"
               placeholder="8/7k/5K2/8/8/8/8/6Q1 b - - 0 1">
        <button type="submit">Set</button>
        <button type="button" id="btn-flip">Flip</button>
        <button type="button" id="btn-back" disabled>Back</button>
      </form>
      <p id="position-summary"></p>
      <h2>Moves</h2>
      <ul id="move-list"></ul>
      <h2>Optimal lines</h2>
      <ol id="lines"></ol>
      <button type="button" id="btn-export-pgn">Download PGN</button>
    </div>
  </section>

  <section id="panel-materials" hidden>
    <ul id="material-list"></ul>
    <div id="material-stats"></div>
  </section>

  <section id="panel-mine" hidden>
    <form id="mine-form">
      <label>Material <input name="material" required placeholder="KQvk"></label>
      <label>dtm <input name="dtm" type="number" min="0" required></label>
      <label>count <input name="count" type="number" min="1"></label>
      <label>starts <input name="starts" type="number" min="1"></label>
      <label>ends <input name="ends" type="number" min="1"></label>
      <label>max <input name="max" type="number" min="1" value="50"></label>
      <button type="submit">Search</button>
    </form>
    <p id="mine-status"></p>
    <ul id="mine-results"></ul>
    <button type="button" id="btn-export-fens">Download FENs</button>
    <button type="button" id="btn-export-csv">Download CSV</button>
  </section>
</main>
</body>
</html>
```

`web/css/app.css` — enough for a usable two-column layout; keep it small and readable:

```css
:root { --fg: #222; --muted: #666; --accent: #1a6; --bg: #fff; --panel: #f6f6f6; }
* { box-sizing: border-box; }
body { margin: 0; font: 15px/1.5 system-ui, sans-serif; color: var(--fg); background: var(--bg); }
header { display: flex; align-items: baseline; gap: 1.5rem; padding: .75rem 1rem; border-bottom: 1px solid #ddd; }
header h1 { font-size: 1.1rem; margin: 0; }
nav button { border: 0; background: none; padding: .4rem .7rem; cursor: pointer; border-radius: 4px; }
nav button.active { background: var(--panel); font-weight: 600; }
main { padding: 1rem; }
#panel-explorer { display: flex; gap: 1.5rem; flex-wrap: wrap; }
#board { width: min(90vw, 480px); aspect-ratio: 1; }
.side { flex: 1 1 320px; min-width: 300px; }
#fen-input { width: 100%; font-family: ui-monospace, monospace; }
#move-list { list-style: none; padding: 0; display: flex; flex-wrap: wrap; gap: .35rem; }
#move-list li { border: 1px solid #ddd; border-radius: 4px; padding: .2rem .5rem; cursor: pointer; }
#move-list li.optimal { border-color: var(--accent); font-weight: 600; }
#move-list li.dead { color: var(--muted); cursor: default; }
#error-banner { background: #fee; border-bottom: 1px solid #f99; padding: .6rem 1rem; }
#error-banner.info { background: #eef; border-color: #99f; }
#material-list, #mine-results { list-style: none; padding: 0; font-family: ui-monospace, monospace; }
#mine-results li, #material-list li { padding: .2rem 0; cursor: pointer; }
label { display: inline-block; margin-right: .75rem; }
```

`server/helpmate_server/app.py` — mount static files at the END of `create_app`, after every `/v1` route is registered (order matters: a mount at `/` would otherwise shadow them):

```python
    # Dashboard. Mounted last so /v1 routes keep priority; html=True serves
    # index.html for "/". Absent in a source checkout without web/, so guard it.
    web_dir = Path(__file__).resolve().parents[2] / "web"
    if web_dir.is_dir():
        app.mount("/", StaticFiles(directory=str(web_dir), html=True), name="web")
```

with `from pathlib import Path` and `from fastapi.staticfiles import StaticFiles` at the top.

**Note to implementer:** verify the `parents[2]` hop actually resolves to the repo's `web/` from the installed package layout (`server/helpmate_server/app.py` → repo root). Print it once while developing; if the editable install resolves elsewhere, use `importlib.resources` or an explicit `--web-dir` option on `helpmate-server` instead, and say which you chose in your report.

- [ ] **Step 4: Run it**

```
taskset -c 0-3 python -m pytest tests/server -v
```
Expected: all pass, including the three new tests.

- [ ] **Step 5: Commit**

```bash
git add web/index.html web/css/app.css server/helpmate_server/app.py tests/server/test_static.py
git commit   # feat(web): page shell served by the API process
```

---

### Task 4: Pure JS helpers + Node tests

**Files:**
- Create: `web/js/lib/state.js`, `web/js/lib/export.js`, `tests/js/state.test.js`, `tests/js/export.test.js`
- Modify: `Makefile` (a `jstest` target)

**Interfaces:**
- Produces (ES modules, no DOM access, importable by `node --test`):
  - `state.js`: `encodeState({fen, panel}) -> string` (the URL hash, e.g. `#fen=...&panel=explorer`), `decodeState(hash) -> {fen, panel}` (missing → `{fen: null, panel: "explorer"}`).
  - `export.js`: `toPgn(fen, lines) -> string`, `toFenList(fens) -> string`, `toCsv(rows) -> string` where `rows` is an array of `{fen, dtm, count}`.

- [ ] **Step 1: Write the failing tests**

`tests/js/state.test.js`:

```js
import test from "node:test";
import assert from "node:assert/strict";
import { encodeState, decodeState } from "../../web/js/lib/state.js";

const FEN = "8/7k/5K2/8/8/8/8/6Q1 b - - 0 1";

test("round-trips a position through the hash", () => {
  const hash = encodeState({ fen: FEN, panel: "explorer" });
  assert.ok(hash.startsWith("#"));
  assert.deepEqual(decodeState(hash), { fen: FEN, panel: "explorer" });
});

test("encodes spaces and slashes safely", () => {
  const hash = encodeState({ fen: FEN, panel: "explorer" });
  assert.ok(!hash.includes(" "), "raw spaces would break the URL");
});

test("defaults when the hash is empty or unknown", () => {
  assert.deepEqual(decodeState(""), { fen: null, panel: "explorer" });
  assert.deepEqual(decodeState("#"), { fen: null, panel: "explorer" });
  assert.equal(decodeState("#panel=mine").panel, "mine");
});
```

`tests/js/export.test.js`:

```js
import test from "node:test";
import assert from "node:assert/strict";
import { toPgn, toFenList, toCsv } from "../../web/js/lib/export.js";

const FEN = "8/7k/5K2/8/8/8/8/6Q1 b - - 0 1";

test("PGN carries the position and one movetext per line", () => {
  const pgn = toPgn(FEN, [["Kh6", "Qh2#"], ["Kh8", "Qg7#"]]);
  assert.ok(pgn.includes(`[FEN "${FEN}"]`));
  assert.ok(pgn.includes("[SetUp \"1\"]"));
  // black moves first in a helpmate, so movetext starts with "1..."
  assert.ok(pgn.includes("1... Kh6 2. Qh2#"), pgn);
  assert.equal(pgn.split("[Event").length - 1, 2, "one game per line");
});

test("FEN list is one position per line, newline-terminated", () => {
  assert.equal(toFenList([FEN, FEN]), `${FEN}\n${FEN}\n`);
  assert.equal(toFenList([]), "");
});

test("CSV has a header and quotes the FEN field", () => {
  const csv = toCsv([{ fen: FEN, dtm: 2, count: 4 }]);
  const [head, row] = csv.trim().split("\n");
  assert.equal(head, "fen,dtm,count");
  assert.equal(row, `"${FEN}",2,4`);
});
```

- [ ] **Step 2: Run them**

`node --test tests/js/` → FAILS: cannot find module `../../web/js/lib/state.js`.

- [ ] **Step 3: Implement**

`web/js/lib/state.js`:

```js
// URL <-> view state. The position lives in the hash so a link is shareable
// and the browser's back button navigates position history.
export function encodeState({ fen, panel = "explorer" }) {
  const p = new URLSearchParams();
  if (fen) p.set("fen", fen);
  if (panel && panel !== "explorer") p.set("panel", panel);
  const s = p.toString();
  return s ? `#${s}` : "#";
}

export function decodeState(hash) {
  const p = new URLSearchParams((hash || "").replace(/^#/, ""));
  return { fen: p.get("fen"), panel: p.get("panel") || "explorer" };
}
```

`web/js/lib/export.js`:

```js
// Client-side exports. No network, no DOM -- callers wrap the result in a Blob.

// One PGN game per optimal line. Helpmates start with Black, so the movetext
// opens with "1..." and each pair of plies is one numbered move.
export function toPgn(fen, lines) {
  return lines.map((line) => {
    const parts = [];
    for (let i = 0; i < line.length; i++) {
      const moveNo = Math.floor(i / 2) + 1;
      if (i === 0) parts.push(`${moveNo}... ${line[i]}`);
      else if (i % 2 === 1) parts.push(`${moveNo + 1}. ${line[i]}`);
      else parts.push(`${moveNo}... ${line[i]}`);
    }
    return [
      '[Event "helpmate"]',
      '[SetUp "1"]',
      `[FEN "${fen}"]`,
      "",
      `${parts.join(" ")} *`,
      "",
    ].join("\n");
  }).join("\n");
}

export function toFenList(fens) {
  return fens.map((f) => `${f}\n`).join("");
}

export function toCsv(rows) {
  const esc = (v) => (typeof v === "string" ? `"${v.replace(/"/g, '""')}"` : String(v));
  const head = "fen,dtm,count";
  const body = rows.map((r) => [esc(r.fen), r.dtm, r.count].join(",")).join("\n");
  return rows.length ? `${head}\n${body}\n` : `${head}\n`;
}
```

**Note to implementer:** the PGN numbering above is the one the test pins (`1... Kh6 2. Qh2#`). Run the test and make the code satisfy it; if you find the numbering genuinely wrong for chess-composition PGN, say so in your report with a reference rather than quietly changing both sides.

- [ ] **Step 4: Run them**

```
node --test tests/js/
```
Expected: all pass.

Add to `Makefile`:

```make
jstest:
	node --test tests/js/
.PHONY: jstest
```
(append `jstest` to the existing `.PHONY` line if the file uses a single one.)

- [ ] **Step 5: Commit**

```bash
git add web/js/lib tests/js Makefile
git commit   # feat(web): pure URL-state and export helpers with node tests
```

---

### Task 5: API client module

**Files:**
- Create: `web/js/api.js`
- Test: covered end-to-end in Task 8 (this module is thin and network-bound; no separate unit test)

**Interfaces:**
- Produces:
  ```js
  export class ApiError extends Error { constructor(status, code, message, hint) }
  export async function getJson(path, params)      // throws ApiError; returns {status, body}
  export const api = {
    health(), materials(), stats(name),
    probe(fen), line(fen, all), moves(fen),
    mine({material, dtm, count, starts, ends, max}),
  };
  ```
  `getJson` returns `{status, body}` rather than throwing on 202, so callers can implement the fetching-poll; it throws `ApiError` for 4xx/5xx with the envelope's `code`, `message` and `hint`.

- [ ] **Step 1: Implement (no unit test — Task 8 covers it end to end)**

`web/js/api.js`:

```js
// Thin wrapper over the read-only API. Two rules the UI depends on:
//   * 202 is NOT an error -- it means "the table is downloading"; the caller
//     polls. We return the status so callers can branch.
//   * 4xx/5xx carry the {"error": {code, message, hint}} envelope; we turn
//     that into an ApiError so every screen can render it the same way.
export class ApiError extends Error {
  constructor(status, code, message, hint) {
    super(message || `HTTP ${status}`);
    this.status = status; this.code = code; this.hint = hint || null;
  }
}

export async function getJson(path, params = {}) {
  const url = new URL(path, window.location.origin);
  for (const [k, v] of Object.entries(params))
    if (v !== undefined && v !== null && v !== "") url.searchParams.set(k, v);
  const res = await fetch(url);
  let body = null;
  try { body = await res.json(); } catch { /* empty or non-JSON body */ }
  if (res.status >= 400) {
    const e = body && body.error ? body.error : {};
    throw new ApiError(res.status, e.code || "error", e.message || res.statusText, e.hint);
  }
  return { status: res.status, body };
}

export const api = {
  health: () => getJson("/v1/health"),
  materials: () => getJson("/v1/materials"),
  stats: (name) => getJson(`/v1/materials/${encodeURIComponent(name)}/stats`),
  probe: (fen) => getJson("/v1/probe", { fen }),
  line: (fen, all = false) => getJson("/v1/line", { fen, all: all ? "true" : "" }),
  moves: (fen) => getJson("/v1/moves", { fen }),
  mine: (q) => getJson("/v1/mine", q),
};
```

- [ ] **Step 2: Syntax check**

```
node --input-type=module -e "$(sed 's/window.location.origin/\"http:\/\/x\"/' web/js/api.js) ; console.log(typeof api.moves)"
```
Expected: prints `function` (this only proves the module parses and exports; behaviour is covered in Task 8).

- [ ] **Step 3: Commit**

```bash
git add web/js/api.js
git commit   # feat(web): API client with envelope-aware errors and 202 passthrough
```

---

### Task 6: Explorer (board, move list, lines)

**Files:**
- Create: `web/js/explorer.js`, `web/vendor/cm-chessboard/` (vendored), `web/vendor/README.md`
- Modify: `web/index.html` (module script tags)

**Interfaces:**
- Consumes: `api` (Task 5), `encodeState`/`decodeState` (Task 4), `toPgn` (Task 4).
- Produces: `export function initExplorer()` — wires the board, FEN form, move list, lines and PGN download; reads and writes `location.hash`; exposes `window.__explorerReady` (a Promise resolving after the first render) purely so Task 8's browser tests can await a settled UI without sleeping.

- [ ] **Step 1: Vendor the board library**

```bash
mkdir -p web/vendor
cd /tmp && npm pack cm-chessboard@8.7.5 && tar xzf cm-chessboard-8.7.5.tgz
cd /home/os/development/8pieces-helpmate
cp -r /tmp/package/src web/vendor/cm-chessboard
cp -r /tmp/package/assets web/vendor/cm-chessboard/assets
cp /tmp/package/LICENSE web/vendor/cm-chessboard/LICENSE
```
Then write `web/vendor/README.md`:

```markdown
# Vendored third-party code

| Package | Version | License | Source |
|---|---|---|---|
| cm-chessboard | 8.7.5 | MIT (see cm-chessboard/LICENSE) | https://github.com/shaack/cm-chessboard |

Vendored deliberately: the dashboard has no build step and must work offline,
so nothing is fetched from a CDN at runtime. To update, re-run the `npm pack`
recipe in `docs/superpowers/plans/2026-07-31-web-dashboard.md` (Task 6) with a
new version and re-run the browser tests.
```

**Note to implementer:** verify the extracted paths — the tarball's layout may differ by version. What must end up true: `web/vendor/cm-chessboard/Chessboard.js` (or the equivalent entry module) is importable from a browser via a relative path, and the piece sprite file it references resolves. Check the version you actually vendored and record it in `web/vendor/README.md`; if 8.7.5 is unavailable, use the current release and note the version. If `npm pack` cannot reach the registry, report BLOCKED rather than hand-writing a board.

- [ ] **Step 2: Write the explorer**

`web/js/explorer.js`:

```js
import { Chessboard, INPUT_EVENT_TYPE, COLOR } from "../vendor/cm-chessboard/Chessboard.js";
import { api, ApiError } from "./api.js";
import { encodeState, decodeState } from "./lib/state.js";
import { toPgn } from "./lib/export.js";

const START = "8/7k/5K2/8/8/8/8/6Q1 b - - 0 1";
let board = null;
let current = START;
let lastMoves = [];      // the move list from the last /v1/moves call, for drag input
const history = [];

function showError(err) {
  const el = document.getElementById("error-banner");
  el.hidden = false;
  el.classList.toggle("info", false);
  el.textContent = err.hint ? `${err.message} — ${err.hint}` : err.message;
}
function showInfo(text) {
  const el = document.getElementById("error-banner");
  el.hidden = false; el.classList.add("info"); el.textContent = text;
}
function clearBanner() {
  const el = document.getElementById("error-banner");
  el.hidden = true; el.textContent = ""; el.classList.remove("info");
}

async function render(fen, { push = true } = {}) {
  current = fen;
  document.getElementById("fen-input").value = fen;
  board.setPosition(fen.split(" ")[0], true);
  document.getElementById("btn-back").disabled = history.length === 0;
  if (push) location.hash = encodeState({ fen, panel: "explorer" });

  const summary = document.getElementById("position-summary");
  const moveList = document.getElementById("move-list");
  const linesEl = document.getElementById("lines");
  moveList.textContent = ""; linesEl.textContent = "";

  let res;
  try {
    res = await api.moves(fen);
  } catch (err) {
    if (err instanceof ApiError) { showError(err); summary.textContent = ""; return; }
    throw err;
  }
  if (res.status === 202) {
    showInfo(`downloading ${res.body.material}…`);
    setTimeout(() => render(fen, { push: false }), 1500);
    return;
  }
  clearBanner();

  const b = res.body;
  lastMoves = b.moves;
  summary.textContent = b.solvable === false
    ? "unsolvable"
    : `dtm ${b.dtm} (${b.notation}) · ${b.count} optimal line(s)` +
      (b.flipped ? " · colors flipped" : "");

  for (const m of b.moves) {
    const li = document.createElement("li");
    li.textContent = m.solvable ? `${m.san} → ${m.notation}` : `${m.san} → –`;
    li.className = m.optimal ? "optimal" : (m.solvable ? "" : "dead");
    li.dataset.san = m.san;
    li.addEventListener("click", () => { history.push(current); render(m.fen); });
    moveList.appendChild(li);
  }

  if (b.solvable !== false) {
    try {
      const ls = await api.line(fen, true);
      for (const line of ls.body.lines) {
        const li = document.createElement("li");
        li.textContent = line.join(" ");
        linesEl.appendChild(li);
      }
      linesEl.dataset.lines = JSON.stringify(ls.body.lines);
    } catch (err) { if (!(err instanceof ApiError)) throw err; }
  }
}

export function initExplorer() {
  board = new Chessboard(document.getElementById("board"), {
    position: START.split(" ")[0],
    assetsUrl: "/vendor/cm-chessboard/assets/",
    style: { borderType: "frame" },
  });

  // Dragging a piece plays the corresponding legal move, when there is one.
  // The board is a view over the server's move list: we never invent a move
  // client-side, we look up the drag in what /v1/moves returned.
  board.enableMoveInput((event) => {
    if (event.type !== INPUT_EVENT_TYPE.validateMoveInput) return true;
    const uci = `${event.squareFrom}${event.squareTo}`;
    const hit = (lastMoves || []).find((m) => m.uci === uci || m.uci.startsWith(uci));
    if (!hit) return false;               // not a legal move: snap back
    history.push(current);
    render(hit.fen);
    return true;
  });

  document.getElementById("fen-form").addEventListener("submit", (e) => {
    e.preventDefault();
    history.push(current);
    render(document.getElementById("fen-input").value.trim());
  });
  document.getElementById("btn-flip").addEventListener("click", () => {
    board.setOrientation(board.getOrientation() === COLOR.white ? COLOR.black : COLOR.white);
  });
  document.getElementById("btn-back").addEventListener("click", () => {
    const prev = history.pop();
    if (prev) render(prev);
  });
  document.getElementById("btn-export-pgn").addEventListener("click", () => {
    const lines = JSON.parse(document.getElementById("lines").dataset.lines || "[]");
    const blob = new Blob([toPgn(current, lines)], { type: "application/x-chess-pgn" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "helpmate.pgn";
    a.click();
    URL.revokeObjectURL(a.href);
  });
  window.addEventListener("hashchange", () => {
    const { fen } = decodeState(location.hash);
    if (fen && fen !== current) render(fen, { push: false });
  });

  const { fen } = decodeState(location.hash);
  window.__explorerReady = render(fen || START, { push: !fen });
}
```

Add to `web/index.html` before `</body>`:

```html
<script type="module">
  import { initExplorer } from "/js/explorer.js";
  initExplorer();
</script>
```

**Note to implementer:** cm-chessboard's import names and constructor options vary between major versions (`Chessboard`, `INPUT_EVENT_TYPE`, `COLOR`, `assetsUrl` vs `sprite.url`). Read the version you vendored and adapt these lines to its actual API — the behaviour above is the contract, not the exact option names. Piece *dragging* (editing the position by hand) is wired in Task 8's checklist only if the vendored version supports it without extra plumbing; the FEN box and move clicking are the required paths.

- [ ] **Step 3: Verify by hand**

```bash
D=$(mktemp -d); ./build/helpmate gen KQvk --tables $D >/dev/null
helpmate-server --tables $D --port 8791 &
sleep 3
curl -s localhost:8791/ | grep -c 'id="board"'      # 1
curl -s "localhost:8791/v1/moves?fen=8/7k/5K2/8/8/8/8/6Q1%20b%20-%20-%200%201" | head -c 200
kill %1; rm -rf $D
```
Then open `http://127.0.0.1:8791/` in a browser once and confirm the board renders and clicking a move advances it. Paste what you saw into your report.

- [ ] **Step 4: Commit**

```bash
git add web/js/explorer.js web/vendor web/index.html
git commit   # feat(web): position explorer with board, move list and lines
```

---

### Task 7: Material browser and mine search

**Files:**
- Create: `web/js/materials.js`, `web/js/mine.js`
- Modify: `web/index.html` (import both; panel switching)

**Interfaces:**
- Consumes: `api` (Task 5), `toFenList`/`toCsv` (Task 4), `encodeState` (Task 4).
- Produces: `export function initMaterials()` and `export function initMine()`; a shared `showPanel(name)` in `web/js/panels.js` used by the nav buttons and by deep links (`#panel=mine`).

- [ ] **Step 1: Implement panel switching**

`web/js/panels.js`:

```js
import { decodeState, encodeState } from "./lib/state.js";

export function showPanel(name) {
  for (const btn of document.querySelectorAll("nav button"))
    btn.classList.toggle("active", btn.dataset.panel === name);
  for (const id of ["explorer", "materials", "mine"])
    document.getElementById(`panel-${id}`).hidden = id !== name;
}

export function initPanels() {
  for (const btn of document.querySelectorAll("nav button"))
    btn.addEventListener("click", () => {
      const name = btn.dataset.panel;
      const { fen } = decodeState(location.hash);
      location.hash = encodeState({ fen, panel: name });
      showPanel(name);
    });
  showPanel(decodeState(location.hash).panel);
  window.addEventListener("hashchange", () => showPanel(decodeState(location.hash).panel));
}
```

- [ ] **Step 2: Implement the material browser**

`web/js/materials.js`:

```js
import { api, ApiError } from "./api.js";
import { encodeState } from "./lib/state.js";

function fmtSize(n) {
  if (n >= 1e9) return `${(n / 1e9).toFixed(2)} GB`;
  if (n >= 1e6) return `${(n / 1e6).toFixed(1)} MB`;
  if (n >= 1e3) return `${(n / 1e3).toFixed(1)} kB`;
  return `${n} B`;
}

async function showStats(name) {
  const box = document.getElementById("material-stats");
  box.textContent = "loading…";
  let res;
  try { res = await api.stats(name); }
  catch (err) {
    if (err instanceof ApiError) { box.textContent = err.hint ? `${err.message} — ${err.hint}` : err.message; return; }
    throw err;
  }
  if (res.status === 202) { box.textContent = `downloading ${name}…`; setTimeout(() => showStats(name), 1500); return; }
  const s = res.body;
  box.textContent = "";
  const h = document.createElement("h2"); h.textContent = `${s.material} — max_dtm ${s.max_dtm}`;
  box.appendChild(h);
  const samples = document.createElement("ul");
  samples.id = "material-samples";
  for (const fen of (s.deepest || []).concat(s.deepest_unique || [])) {
    const li = document.createElement("li");
    li.textContent = fen;
    li.addEventListener("click", () => { location.hash = encodeState({ fen, panel: "explorer" }); });
    samples.appendChild(li);
  }
  box.appendChild(samples);
}

export async function initMaterials() {
  const list = document.getElementById("material-list");
  list.textContent = "loading…";
  let res;
  try { res = await api.materials(); }
  catch (err) { list.textContent = err.message; return; }
  list.textContent = "";
  for (const m of res.body.materials) {
    const li = document.createElement("li");
    li.textContent = `${m.material}  ${m.pieces} pieces  ${fmtSize(m.size_bytes)}  ${m.location}`;
    li.dataset.material = m.material;
    li.addEventListener("click", () => showStats(m.material));
    list.appendChild(li);
  }
  window.__materialsReady = true;
}
```

- [ ] **Step 3: Implement mine search**

`web/js/mine.js`:

```js
import { api, ApiError } from "./api.js";
import { encodeState } from "./lib/state.js";
import { toFenList, toCsv } from "./lib/export.js";

let rows = [];

function validate(q) {
  // Mirrors the server's rules so an obvious mistake never costs a round trip.
  // The server remains the authority; its 400 is displayed if we miss something.
  for (const k of ["starts", "ends"]) {
    if (q[k] === "" || q[k] === undefined) continue;
    const v = Number(q[k]);
    if (!Number.isInteger(v) || v < 1) return `${k} must be at least 1`;
    if (q.count !== "" && Number.isInteger(Number(q.count)) && v > Number(q.count))
      return `${k} cannot exceed count ${q.count}`;
  }
  return null;
}

export function initMine() {
  const form = document.getElementById("mine-form");
  const status = document.getElementById("mine-status");
  const results = document.getElementById("mine-results");

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const q = Object.fromEntries(new FormData(form).entries());
    results.textContent = ""; rows = [];
    const bad = validate(q);
    if (bad) { status.textContent = bad; return; }
    status.textContent = "searching…";
    let res;
    try { res = await api.mine(q); }
    catch (err) {
      if (err instanceof ApiError) { status.textContent = err.hint ? `${err.message} — ${err.hint}` : err.message; return; }
      throw err;
    }
    if (res.status === 202) { status.textContent = `downloading ${res.body.material}…`; return; }
    const b = res.body;
    rows = b.fens.map((fen) => ({ fen, dtm: Number(q.dtm), count: q.count === "" ? "" : Number(q.count) }));
    status.textContent =
      `${b.fens.length} position(s)` +
      (b.truncated ? " (truncated)" : "") +
      (b.skipped_saturated ? ` · ${b.skipped_saturated} skipped (count saturated)` : "");
    for (const fen of b.fens) {
      const li = document.createElement("li");
      li.textContent = fen;
      li.addEventListener("click", () => { location.hash = encodeState({ fen, panel: "explorer" }); });
      results.appendChild(li);
    }
  });

  const download = (text, name, type) => {
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([text], { type }));
    a.download = name; a.click(); URL.revokeObjectURL(a.href);
  };
  document.getElementById("btn-export-fens")
    .addEventListener("click", () => download(toFenList(rows.map((r) => r.fen)), "helpmate-fens.txt", "text/plain"));
  document.getElementById("btn-export-csv")
    .addEventListener("click", () => download(toCsv(rows), "helpmate-mine.csv", "text/csv"));
}
```

Update the module script in `web/index.html`:

```html
<script type="module">
  import { initPanels } from "/js/panels.js";
  import { initExplorer } from "/js/explorer.js";
  import { initMaterials } from "/js/materials.js";
  import { initMine } from "/js/mine.js";
  initPanels(); initExplorer(); initMaterials(); initMine();
</script>
```

- [ ] **Step 4: Verify by hand**

Start a server as in Task 6 Step 3, open the page, and confirm: the Materials tab lists `KQvk` and `Kvk`; clicking `KQvk` shows its stats and sample positions; a sample position opens in the Explorer; a search for `KQvk dtm 2 count 4 starts 2 ends 4` returns positions; `starts 5 count 2` shows the validation message without a request. Paste what you saw into your report.

- [ ] **Step 5: Commit**

```bash
git add web/js/panels.js web/js/materials.js web/js/mine.js web/index.html
git commit   # feat(web): material browser and mine search with export
```

---

### Task 8: Browser tests

**Files:**
- Create: `tests/ui/conftest.py`, `tests/ui/test_dashboard.py`
- Modify: `pyproject.toml` (add `playwright` to the `dev` extra)

**Interfaces:**
- Consumes: the whole dashboard; `window.__explorerReady` (Task 6) and `window.__materialsReady` (Task 7) as settle signals.
- Produces: a pytest suite driving headless Chromium against a real `helpmate-server`.

- [ ] **Step 1: Write the fixtures and tests**

`tests/ui/conftest.py`:

```python
import socket, subprocess, sys, time
import pytest
import helpmate

@pytest.fixture(scope="session")
def tables(tmp_path_factory):
    d = tmp_path_factory.mktemp("uitables")
    helpmate.generate("KQvk", tables=str(d), threads=2)
    return str(d)

def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]

@pytest.fixture(scope="session")
def server(tables):
    port = _free_port()
    p = subprocess.Popen([sys.executable, "-m", "uvicorn", "--factory",
                          "helpmate_server.main:_app_for_tests", "--port", str(port)],
                         env={"HELPMATE_TABLES": tables, **__import__("os").environ},
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    url = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            import urllib.request
            urllib.request.urlopen(f"{url}/v1/health", timeout=1)
            break
        except Exception:
            time.sleep(0.1)
    else:
        p.kill(); raise RuntimeError("server did not start")
    yield url
    p.terminate(); p.wait(timeout=10)

@pytest.fixture(scope="session")
def browser():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        # --no-sandbox: user namespaces are restricted on the dev machine.
        b = pw.chromium.launch(args=["--no-sandbox"])
        yield b
        b.close()

@pytest.fixture()
def page(browser):
    ctx = browser.new_context()
    pg = ctx.new_page()
    yield pg
    ctx.close()
```

**Note to implementer:** `helpmate_server.main` currently builds the app inside `main()`; add a small `_app_for_tests()` factory there that reads `HELPMATE_TABLES` and returns `create_app(ChainSource([LocalDir(...)]))`, so uvicorn can serve it. Keep it tiny and say in your report that you added it.

`tests/ui/test_dashboard.py`:

```python
import json
from urllib.parse import quote

GOLDEN = "8/7k/5K2/8/8/8/8/6Q1 b - - 0 1"

def test_dashboard_renders_the_initial_position(page, server):
    page.goto(server)
    page.wait_for_function("window.__explorerReady !== undefined")
    page.wait_for_selector("#move-list li")
    assert "dtm 2" in page.inner_text("#position-summary")
    sans = page.eval_on_selector_all("#move-list li", "els => els.map(e => e.dataset.san)")
    assert "Kh6" in sans and "Kh8" in sans
    optimal = page.eval_on_selector_all("#move-list li.optimal", "els => els.map(e => e.dataset.san)")
    assert set(optimal) == {"Kh6", "Kh8"}

def test_clicking_a_move_advances_and_history_returns(page, server):
    page.goto(server)
    page.wait_for_selector("#move-list li.optimal")
    before = page.input_value("#fen-input")
    page.click("#move-list li.optimal")
    page.wait_for_function("document.getElementById('fen-input').value !== arguments[0]", arg=before)
    assert page.input_value("#fen-input") != before
    assert "fen=" in page.url
    page.click("#btn-back")
    page.wait_for_function("document.getElementById('fen-input').value === arguments[0]", arg=before)

def test_a_shared_link_restores_the_position(page, server):
    page.goto(f"{server}/#fen={quote(GOLDEN)}")
    page.wait_for_selector("#move-list li")
    assert page.input_value("#fen-input") == GOLDEN

def test_setting_an_invalid_fen_shows_the_server_message(page, server):
    page.goto(server)
    page.wait_for_selector("#move-list li")
    page.fill("#fen-input", "garbage")
    page.click("#fen-form button[type=submit]")
    page.wait_for_selector("#error-banner:not([hidden])")
    assert page.inner_text("#error-banner")

def test_materials_panel_lists_tables_and_opens_a_sample(page, server):
    page.goto(f"{server}/#panel=materials")
    page.wait_for_function("window.__materialsReady === true")
    names = page.eval_on_selector_all("#material-list li", "els => els.map(e => e.dataset.material)")
    assert "KQvk" in names and "Kvk" in names
    page.click("#material-list li[data-material=KQvk]")
    page.wait_for_selector("#material-samples li")

def test_mine_search_and_client_side_validation(page, server):
    page.goto(f"{server}/#panel=mine")
    page.fill("#mine-form input[name=material]", "KQvk")
    page.fill("#mine-form input[name=dtm]", "2")
    page.fill("#mine-form input[name=count]", "4")
    page.fill("#mine-form input[name=starts]", "2")
    page.fill("#mine-form input[name=ends]", "4")
    page.click("#mine-form button[type=submit]")
    page.wait_for_selector("#mine-results li")
    assert "position(s)" in page.inner_text("#mine-status")

    # starts > count is caught before any request
    page.fill("#mine-form input[name=count]", "2")
    page.fill("#mine-form input[name=starts]", "5")
    page.click("#mine-form button[type=submit]")
    page.wait_for_function(
        "document.getElementById('mine-status').textContent.includes('cannot exceed')")
```

- [ ] **Step 2: Run them**

```
taskset -c 0-3 python -m pytest tests/ui -v
```
Expected: initially FAIL (missing `_app_for_tests`, and whatever DOM details differ); iterate until green. If a test fails because the UI genuinely behaves differently from the spec (not because the selector is wrong), fix the UI — the tests encode the spec's promises.

- [ ] **Step 3: Add the dependency**

`pyproject.toml`: add `"playwright"` to the `dev` extra list.

- [ ] **Step 4: Commit**

```bash
git add tests/ui pyproject.toml server/helpmate_server/main.py
git commit   # test(web): Playwright end-to-end suite for the dashboard
```

---

### Task 9: CI job, docs, changelog, version bump

**Files:**
- Modify: `.github/workflows/ci.yml` (new `ui` job), `docs/USAGE.md`, `README.md`, `CHANGELOG.md`, `pyproject.toml`, `server/helpmate_server/__init__.py`, `tests/server/test_packaging.py`, `src/version.h`, `CMakeLists.txt:2` (+ the `cli_version` ctest regex)

**Interfaces:**
- Consumes: everything above.

- [ ] **Step 1: CI job**

Add to `.github/workflows/ci.yml`, alongside the existing `cpp`/`python`/`coverage` jobs (match their style; `ubuntu-24.04`, `CC: gcc-13`, `CXX: g++-13`):

```yaml
  ui:
    name: Dashboard (browser tests)
    runs-on: ubuntu-24.04
    env:
      CC: gcc-13
      CXX: g++-13
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install package with dev and server extras
        run: python -m pip install .[dev,server]

      # Browsers are cached; --with-deps installs the system libraries the
      # runner image lacks. The cache key follows the playwright version so a
      # driver bump re-downloads rather than using a stale browser.
      - name: Cache Playwright browsers
        uses: actions/cache@v4
        with:
          path: ~/.cache/ms-playwright
          key: playwright-${{ runner.os }}-${{ hashFiles('pyproject.toml') }}
      - name: Install Chromium
        run: python -m playwright install --with-deps chromium

      - name: JS helper tests
        run: node --test tests/js/

      - name: Browser tests
        run: python -m pytest tests/ui -v
```

- [ ] **Step 2: Version bump to 0.7.0**

Six places, all of which must agree: `pyproject.toml`'s `version`, `server/helpmate_server/__init__.py`'s `__version__`, the expected value in `tests/server/test_packaging.py`, `HELPMATE_VERSION` in `src/version.h:9`, `project(helpmate VERSION ...)` in `CMakeLists.txt:2`, and the `cli_version` ctest regex in `CMakeLists.txt`.

- [ ] **Step 3: Docs**

`docs/USAGE.md`: a "Dashboard" section — how to start it (`helpmate-server --tables ~/tb` then open `http://127.0.0.1:8642/`), what each panel does, that positions are shareable via the URL, and the export formats. Document `GET /v1/moves` in the API section with a real captured `curl` example (run it against a scratch server). `README.md`: two lines pointing at the dashboard. `CHANGELOG.md`: a `## [0.7.0] - <date>` section above `[0.6.2]` covering the dashboard, `/v1/moves`, and the browser-test suite.

- [ ] **Step 4: Full verification**

```
PATH="$HOME/.local/bin:$PATH" cmake --build build -j4
taskset -c 0-3 ./build/helpmate_tests "~[slow]"
cd build && taskset -c 0-3 ctest --output-on-failure && cd ..
node --test tests/js/
taskset -c 0-3 python -m pytest tests/python tests/server tests/ui -v
./build/helpmate --version      # helpmate 0.7.0
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))"
```
All must pass before committing.

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/ci.yml docs/USAGE.md README.md CHANGELOG.md \
        pyproject.toml server/helpmate_server/__init__.py tests/server/test_packaging.py \
        src/version.h CMakeLists.txt
git commit   # release: v0.7.0 - web dashboard, /v1/moves, browser tests
```

---

## Deferred from the spec (and why)

The spec's explorer section also lists a **piece palette for adding/removing
pieces** and a **clear-board button** — free position *editing* beyond playing
legal moves. This plan implements position entry through the FEN box and
position movement through the board (drag a piece to play a legal move) but
not free editing, because free editing needs its own model: an arbitrary piece
arrangement is often not a legal position, so the UI would have to represent
"being edited" as a state distinct from "queryable", with its own validation
and error surface. That is a coherent feature, not a checkbox on this one.

Recommendation: ship v0.7 without free editing, then add it as a small v0.7.1
once the explorer has been used in anger — by then it will be clear whether
composers want a palette at all, given a FEN box and a board that plays moves.
Flagged to the user rather than silently dropped.

## Verification checklist (whole plan)

- C++ fast suite, ctest, `node --test`, and the Python + UI pytest suites all green; `helpmate --version` reports 0.7.0.
- `helpmate-server --tables <dir>` serves both the API and the dashboard on one port; `/v1` routes are not shadowed by the static mount.
- The golden position renders with dtm 2, count 4, and exactly two optimal moves; clicking one advances the board and pushes history; the back button returns.
- A `#fen=` link opens that exact position in a fresh tab.
- Mine search returns results, reports truncation and skipped-saturated counts, and rejects `starts > count` before issuing a request.
- Nothing is fetched from a CDN at runtime: `grep -rn "https://" web/ --include=*.html --include=*.js` finds no remote asset references.
