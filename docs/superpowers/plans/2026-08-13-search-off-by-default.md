# Search Off By Default — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make position search opt-in — `/v1/mine` off unless `--enable-mine` is passed — and narrow the CORS wildcard, so the dashboard can be exposed to other people before the `mine` concurrency work is done.

**Architecture:** One new `create_app` parameter gates the endpoint and is reported on `/v1/health`; the dashboard reads that capability from the single health request it already makes at boot and removes the search panel and its nav button from the document. Nothing is deleted — `mine.js`, the endpoint and the CLI `mine` all stay, tested, behind the flag.

**Tech Stack:** FastAPI + uvicorn (Python 3.9+), plain ES modules with no build step, pytest, Playwright, `node --test`.

Implements `docs/superpowers/specs/2026-08-13-deployment-and-search-off-design.md`. Phase B (the deployment container) is a separate plan; it consumes this one's output and must not start until this is merged.

## Global Constraints

- **Max 4 cores.** Every build/test command runs under `taskset -c 0-3`.
- **Never write to `~/tb` or `~/tb/raw`** — a 6-piece generation run is live there. Reading is fine. Scratch goes in `$(mktemp -d)`; never `rm -rf /tmp/tmp.*`.
- **Never run bare `./build/helpmate_tests`** — always `"~[slow]"` or a specific tag.
- **`ctest` runs without `-j`** — documented shared-temp-dir race in `test_probe.cpp`.
- **`make test-web` / `make test-api` reinstall first.** `helpmate-web` and `helpmate-api` install as *copies* into site-packages; a bare `pytest` tests a stale copy.
- Prefix pip/build commands with `GIT_CONFIG_GLOBAL=/dev/null`.
- Never use a `pgrep -f` pattern that matches the grepping command's own line; bracket it (`helpmate[-]server`).
- Branch: `feat/deploy-and-search-off`. Commit trailer, exactly:
  `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`
- Gate before each commit: `make lint`, `make jstest`, `make test-web`, `pytest tests/repo -v`, `pytest src/packages/api/tests -v`.

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `src/packages/api/helpmate_server/app.py` | `enable_mine` + `cors_origins` params; 503 on `/v1/mine`; `mining_enabled` on `/v1/health`; conditional CORS | Modify |
| `src/packages/api/helpmate_server/main.py` | `--enable-mine`, `--cors-origin` flags; `_app_for_tests` reads `HELPMATE_ENABLE_MINE` | Modify |
| `src/packages/api/tests/conftest.py` | `client_mining` fixture | Modify |
| `src/packages/api/tests/test_api_mine.py` | switch to `client_mining`; add default-off tests | Modify |
| `src/packages/api/tests/test_api_themes.py` | switch its 5 `/v1/mine` calls to `client_mining` | Modify |
| `src/packages/api/tests/test_api_cors.py` | CORS default and configured behaviour | **Create** |
| `.../static/js/panels.js` | derive the panel list from the DOM; fall back on an unknown panel | Modify |
| `.../static/js/chip.js` | take an already-fetched health body instead of fetching | Modify |
| `.../static/index.html` | one health fetch at boot; remove search when disabled | Modify |
| `src/packages/web/tests/ui/conftest.py` | `_serve(tables, enable_mine=False)`, `server_mining` fixture | Modify |
| `src/packages/web/tests/ui/test_dashboard.py` | absence tests; 6 search tests move to `server_mining` | Modify |
| `docs/USAGE.md`, `CHANGELOG.md`, `VERSION`, 4 × `pyproject.toml`, 2 × `__init__.py` | document and bump to 0.14.0 | Modify |

---

### Task 1: The server flag, the 503, and the health capability

**Files:**
- Modify: `src/packages/api/helpmate_server/app.py:52-56` (signature), `:153-159` (health), `:405-410` (mine)
- Modify: `src/packages/api/helpmate_server/main.py`
- Modify: `src/packages/api/tests/conftest.py`, `test_api_mine.py`, `test_api_themes.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `create_app(chain, mine_cap=1000, mine_timeout=30.0, web_root=None, serve_web=True, enable_mine=False)`; `/v1/health` gains `"mining_enabled": bool`; `/v1/mine` returns 503 with error code `mining_disabled` when off. Task 3 reads `mining_enabled`.

- [ ] **Step 1: Write the failing tests**

Add to `src/packages/api/tests/test_api_mine.py`:

```python
def test_mine_is_disabled_by_default(client):
    r = client.get("/v1/mine", params={"material": "KQvk", "dtm": 4})
    assert r.status_code == 503
    body = r.json()
    assert body["error"]["code"] == "mining_disabled"
    # The hint must name the flag: a 503 with no way forward is a dead end.
    assert "--enable-mine" in body["error"]["hint"]


def test_health_reports_mining_disabled_by_default(client):
    assert client.get("/v1/health").json()["mining_enabled"] is False


def test_health_reports_mining_enabled_when_on(client_mining):
    assert client_mining.get("/v1/health").json()["mining_enabled"] is True


def test_mine_answers_normally_when_enabled(client_mining):
    r = client_mining.get("/v1/mine", params={"material": "KQvk", "dtm": 4})
    assert r.status_code == 200
    assert "fens" in r.json()
```

Add to `src/packages/api/tests/conftest.py`:

```python
@pytest.fixture()
def client_mining(kqvk_dir) -> TestClient:
    """A server with position search switched on.

    Search is off by default from 0.14.0, so every test that exercises
    /v1/mine needs this rather than `client`. Kept as a separate fixture, not
    a flag on `client`, so the default fixture keeps testing the shipped
    configuration."""
    app = create_app(ChainSource([LocalDir(kqvk_dir)]), enable_mine=True)
    return TestClient(app)
```

- [ ] **Step 2: Run them and watch them fail**

```bash
taskset -c 0-3 python -m pytest src/packages/api/tests/test_api_mine.py -v
```

Expected: the two new `client_mining` tests ERROR with `fixture 'client_mining' not found` until conftest is saved; the two `client` tests FAIL — `assert 200 == 503` and `KeyError: 'mining_enabled'`.

- [ ] **Step 3: Add the parameter, the guard and the health field**

In `app.py`, extend the signature:

```python
def create_app(chain: ChainSource, mine_cap: int = 1000,
               mine_timeout: float = 30.0, web_root: str | None = None,
               serve_web: bool = True, enable_mine: bool = False) -> FastAPI:
```

In `health()`, add one key:

```python
        return {"status": "ok", "version": __version__,
                "mine_timeout": mine_timeout,
                "mining_enabled": enable_mine,
                "tables_local": sum(1 for s in cat if s.location in ("local", "cached")),
                "tables_remote": sum(1 for s in cat if s.location == "remote")}
```

As the **first** statement in `mine()`, before any argument validation — an operator who has turned search off should get the same answer whatever the query says:

```python
        if not enable_mine:
            # 503, not 404: the route exists and the server is simply not
            # offering it. A 404 would tell a client probing the API surface
            # that this build has no search at all, which is false and
            # unfixable from the client's side.
            return JSONResponse(status_code=503, content=error_json(
                "mining_disabled",
                "position search is disabled on this server",
                hint="start helpmate-server with --enable-mine to turn it on"))
```

- [ ] **Step 4: Run the mine tests**

```bash
taskset -c 0-3 python -m pytest src/packages/api/tests/test_api_mine.py -v
```

Expected: the four new tests PASS; the 12 pre-existing tests FAIL with 503 — they use `client`.

- [ ] **Step 5: Move the existing search tests onto `client_mining`**

In `test_api_mine.py`, change every pre-existing test that calls `/v1/mine` to take `client_mining` instead of `client`, renaming the parameter at the call sites inside each body. Do the same for the 5 `/v1/mine` calls in `test_api_themes.py`.

```bash
grep -n "client\b" src/packages/api/tests/test_api_mine.py | head -40
grep -n "v1/mine" src/packages/api/tests/test_api_themes.py
```

Leave tests that only call `/v1/themes` on the plain `client`.

- [ ] **Step 6: Wire the CLI flag and the test factory**

In `main.py`, add the argument and pass it through:

```python
    p.add_argument("--enable-mine", action="store_true",
                   help="enable /v1/mine (position search). Off by default: a "
                        "scan is not interruptible and is not bounded under "
                        "concurrent load")
```

```python
        app = create_app(chain, a.mine_cap, a.mine_timeout,
                         web_root=a.web_root, serve_web=not a.no_web,
                         enable_mine=a.enable_mine)
```

And let the browser fixture ask for it:

```python
def _app_for_tests():
    # Factory for `uvicorn --factory helpmate_server.main:_app_for_tests`,
    # used by the browser test suite (src/packages/web/tests/ui) to serve a
    # real helpmate-server against a scratch tables dir named by the
    # environment. HELPMATE_ENABLE_MINE=1 selects the search-enabled server
    # that the six search tests need.
    tables = os.environ["HELPMATE_TABLES"]
    return create_app(ChainSource([LocalDir(tables)]),
                      enable_mine=os.environ.get("HELPMATE_ENABLE_MINE") == "1")
```

- [ ] **Step 7: Run the whole API suite**

```bash
taskset -c 0-3 make test-api
```

Expected: all pass (105 before + 4 new = 109).

- [ ] **Step 8: Prove the guard bites**

Delete the `if not enable_mine:` block, re-run `test_api_mine.py`, and confirm `test_mine_is_disabled_by_default` fails. Restore it, confirm `git diff` is clean on `app.py` apart from the intended change, and re-run.

- [ ] **Step 9: Commit**

```bash
git add src/packages/api
git commit -m "$(cat <<'EOF'
feat(api): position search is opt-in behind --enable-mine

/v1/mine scans a plane, and three properties make it unsafe to expose:
SIGTERM does not stop a running scan, the timeout is non-deterministic under
load because the worker outlives the response that gave up on it, and nothing
bounds concurrency. Rather than fix that now or delete the feature, it goes
behind a flag that defaults to off everywhere.

Disabled, it answers 503 mining_disabled with a hint naming the flag -- not
404, which would tell a client probing the API surface that this build has no
search at all. /v1/health reports mining_enabled so the dashboard can ask
rather than guess.

Nothing is deleted. The 12 existing search tests move to a client_mining
fixture, so the coverage that lets us switch it back on stays green.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Per-origin CORS, and a concurrency limit that is actually applied

**Files:**
- Modify: `src/packages/api/helpmate_server/app.py:56`, `main.py`
- Create: `src/packages/api/tests/test_api_cors.py`

**Interfaces:**
- Consumes: `create_app` from Task 1.
- Produces: `create_app(..., cors_origins: list[str] | None = None)`. With none given, `CORSMiddleware` is **not installed**. Also `--limit-concurrency N`, forwarded to uvicorn — the deployment plan's compose file depends on this existing.

- [ ] **Step 1: Write the failing test**

Create `src/packages/api/tests/test_api_cors.py`:

```python
"""CORS is opt-in per origin.

allow_origins=["*"] let any website read this API from a visitor's browser.
For a public read-only API that is a defensible choice, but it should be one
an operator makes, not the default they inherit."""
from fastapi.testclient import TestClient
from helpmate_server.storage import LocalDir, ChainSource
from helpmate_server.app import create_app


def test_no_cors_header_by_default(client):
    r = client.get("/v1/health", headers={"Origin": "https://evil.example"})
    assert r.status_code == 200
    assert "access-control-allow-origin" not in r.headers


def test_configured_origin_is_allowed(kqvk_dir):
    app = create_app(ChainSource([LocalDir(kqvk_dir)]),
                     cors_origins=["https://helpmate-tb.semantcon.org"])
    c = TestClient(app)
    r = c.get("/v1/health",
              headers={"Origin": "https://helpmate-tb.semantcon.org"})
    assert r.headers["access-control-allow-origin"] == \
        "https://helpmate-tb.semantcon.org"


def test_other_origins_stay_blocked_when_one_is_configured(kqvk_dir):
    app = create_app(ChainSource([LocalDir(kqvk_dir)]),
                     cors_origins=["https://helpmate-tb.semantcon.org"])
    c = TestClient(app)
    r = c.get("/v1/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in r.headers
```

- [ ] **Step 2: Run it and watch it fail**

```bash
taskset -c 0-3 python -m pytest src/packages/api/tests/test_api_cors.py -v
```

Expected: `test_no_cors_header_by_default` FAILS — the wildcard middleware answers `*`.

- [ ] **Step 3: Make the middleware conditional**

Replace `app.py:56` with:

```python
    # Not installed at all when no origin is configured. The dashboard is
    # served from this same origin, so it needs no CORS header; anything that
    # does need one is a cross-origin caller an operator has decided to allow.
    if cors_origins:
        app.add_middleware(CORSMiddleware, allow_origins=list(cors_origins),
                           allow_methods=["GET"])
```

and extend the signature:

```python
def create_app(chain: ChainSource, mine_cap: int = 1000,
               mine_timeout: float = 30.0, web_root: str | None = None,
               serve_web: bool = True, enable_mine: bool = False,
               cors_origins: list[str] | None = None) -> FastAPI:
```

- [ ] **Step 4: Run the test**

```bash
taskset -c 0-3 python -m pytest src/packages/api/tests/test_api_cors.py -v
```

Expected: 3 PASS.

- [ ] **Step 5: Wire the CLI flag**

```python
    p.add_argument("--cors-origin", action="append", default=[],
                   metavar="ORIGIN",
                   help="allow cross-origin GETs from ORIGIN (repeatable). "
                        "Omit for same-origin only")
```

```python
        app = create_app(chain, a.mine_cap, a.mine_timeout,
                         web_root=a.web_root, serve_web=not a.no_web,
                         enable_mine=a.enable_mine,
                         cors_origins=a.cors_origin)
```

- [ ] **Step 5b: Forward a concurrency limit to uvicorn**

`_run` currently calls `uvicorn.run(app, host=host, port=port)` and nothing
else, so a deployment has no way to bound connection count. The container plan
needs one, and a limit that is accepted but ignored is worse than no limit:

```python
def _run(app, host: str, port: int, limit_concurrency: int | None = None) -> None:
    import uvicorn
    # None means uvicorn's own default (unbounded). A deployment that wants a
    # ceiling passes one; nothing is silently capped for a local user.
    uvicorn.run(app, host=host, port=port, limit_concurrency=limit_concurrency)
```

```python
    p.add_argument("--limit-concurrency", type=int, default=None, metavar="N",
                   help="refuse connections beyond N in flight (default: "
                        "unlimited). Set this when exposing the server")
```

```python
    _run(app, a.host, a.port, a.limit_concurrency)
```

Verify argparse accepts it rather than assuming:

```bash
taskset -c 0-3 helpmate-server --help | grep -A1 "limit-concurrency"
```

- [ ] **Step 6: Run the full API suite and the dashboard suite**

```bash
taskset -c 0-3 make test-api && taskset -c 0-3 make test-web
```

Expected: API 112, dashboard 92. The dashboard is same-origin, so dropping the wildcard must not change it — if any UI test fails here, the browser was relying on a CORS header it should never have needed, and that is a real finding, not a test to relax.

- [ ] **Step 7: Commit**

```bash
git add src/packages/api
git commit -m "$(cat <<'EOF'
feat(api): CORS is opt-in per origin, not a wildcard

allow_origins=["*"] let any website read this API from a visitor's browser.
For a public read-only API that is defensible, but it should be a decision an
operator makes rather than the default they inherit -- so --cors-origin is
repeatable and the middleware is not installed at all when none is given.

The dashboard is served from the same origin and needs no CORS header, which
the dashboard suite confirms: 92 browser tests pass with the wildcard gone.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: The dashboard removes search when the server has it off

**Files:**
- Modify: `.../static/js/panels.js:40-46`, `.../static/js/chip.js`, `.../static/index.html:195-203`
- Modify: `src/packages/web/tests/ui/conftest.py:49-89`, `test_dashboard.py`

**Interfaces:**
- Consumes: `mining_enabled` on `/v1/health` (Task 1).
- Produces: `initServerChip(health)` — takes an already-fetched health body or `null`, and is **no longer async**. `showPanel(name)` falls back to `"explorer"` when `name` names no section in the document.

**Why removal and not hiding:** round 1 established the failure mode. Hiding the Search button left the Enter key submitting the form and an orphaned `setInterval` overwriting `#mine-status` forever. A form that is not in the document cannot be submitted and its ticker never starts.

- [ ] **Step 1: Write the failing tests**

Add to `src/packages/web/tests/ui/test_dashboard.py`:

```python
def test_search_is_absent_not_hidden_when_mining_is_disabled(page, server):
    """Absence, not display:none. A hidden form still submits on Enter --
    that exact bug shipped once and left a ticker running forever."""
    page.goto(server)
    page.wait_for_function("() => window.__chipReady === true")
    assert page.locator("nav[aria-label='Screens'] button").count() == 4
    assert page.locator("nav button[data-panel='mine']").count() == 0
    assert page.locator("#panel-mine").count() == 0
    assert page.locator("#mine-form").count() == 0


def test_a_stale_search_deep_link_lands_on_the_explorer(page, server):
    """#panel=mine is a URL people may have bookmarked. With the panel gone it
    must not blank the page -- showPanel would otherwise set .hidden on a null
    and take the whole nav down with it."""
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(f"{server}/#panel=mine")
    page.wait_for_function("() => window.__chipReady === true")
    assert page.locator("#panel-explorer").is_visible()
    assert errors == []


def test_search_is_present_when_the_server_enables_it(page, server_mining):
    page.goto(server_mining)
    page.wait_for_function("() => window.__chipReady === true")
    assert page.locator("nav[aria-label='Screens'] button").count() == 5
    assert page.locator("#panel-mine").count() == 1
```

- [ ] **Step 2: Add the mining-enabled server fixture**

In `src/packages/web/tests/ui/conftest.py`, give `_serve` a parameter and add one fixture:

```python
def _serve(tables, enable_mine=False):
    port = _free_port()
    log = tempfile.TemporaryFile(mode="w+")
    p = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "--factory",
         "helpmate_server.main:_app_for_tests", "--port", str(port)],
        env={**os.environ, "HELPMATE_TABLES": tables,
             "HELPMATE_ENABLE_MINE": "1" if enable_mine else "0"},
        stdout=log, stderr=subprocess.STDOUT,
    )
```

```python
@pytest.fixture(scope="session")
def server_mining(tables):
    """Search is off by default from 0.14.0, so the tests that exercise it
    need a server that has opted in. Session-scoped like the others: this is
    a second uvicorn, not a second corpus."""
    yield from _serve(tables, enable_mine=True)
```

- [ ] **Step 3: Run the new tests and watch them fail**

```bash
taskset -c 0-3 make test-web 2>&1 | tail -30
```

Expected: the two absence tests FAIL (5 buttons found, `#panel-mine` count 1) and the deep-link test PASSES for the wrong reason — the panel still exists. That third one only becomes meaningful after Step 4, which is why Step 6 re-runs it.

- [ ] **Step 4: Derive the panel list from the DOM**

In `panels.js`, replace the hardcoded id list in `showPanel`:

```js
// Derived from the document, never hardcoded: a server with search disabled
// removes #panel-mine and its nav button before initPanels() runs, and a
// hardcoded "mine" would make getElementById return null here and throw --
// taking showPanel, the nav and every other screen down with it.
function panelIds() {
  return [...document.querySelectorAll("section[id^='panel-']")]
    .map((s) => s.id.slice("panel-".length));
}

export function showPanel(name) {
  const ids = panelIds();
  // A bookmarked #panel=mine must land somewhere real rather than hiding
  // every section and painting a blank page.
  if (!ids.includes(name)) name = "explorer";
  activePanel = name;
  for (const btn of document.querySelectorAll("nav button"))
    btn.classList.toggle("active", btn.dataset.panel === name);
  for (const id of ids)
    document.getElementById(`panel-${id}`).hidden = id !== name;
  const fns = pending.get(name);
  if (!fns) return;
  pending.delete(name);   // one shot: revisiting a panel must not re-run its init
  for (const fn of fns) fn();
}
```

- [ ] **Step 5: Fetch health once at boot and act on it**

In `chip.js`, take the body instead of fetching it:

```js
// A one-line answer to "is the server there, and does it have anything?".
// Failure is not an error banner: the rest of the page will surface its own
// errors on the first real request, and a red chip says it once, quietly.
//
// The health body is passed in rather than fetched: index.html needs the same
// response to decide whether search exists, and one boot makes one request.
export function initServerChip(health) {
  const el = document.getElementById("server-chip");
  const corpus = document.getElementById("footer-corpus");
  if (health) {
    const remote = health.tables_remote ? ` · ${health.tables_remote} remote` : "";
    el.textContent = `v${health.version} · ${health.tables_local} tables${remote}`;
    el.classList.remove("down");
    if (corpus) {
      const total = health.tables_local + (health.tables_remote || 0);
      corpus.textContent = `The corpus holds ${total} tables ` +
        `(${health.tables_local} local${remote}).`;
    }
  } else {
    el.textContent = "server unreachable";
    el.classList.add("down");
    if (corpus) corpus.textContent = "";
  }
  el.hidden = false;
  window.__chipReady = true;
}
```

Replace the boot script in `index.html`:

```html
<script type="module">
  import { api } from "/js/api.js";
  import { initPanels } from "/js/panels.js";
  import { initExplorer } from "/js/explorer.js";
  import { initPuzzles } from "/js/puzzle.js";
  import { initMaterials } from "/js/materials.js";
  import { initMine } from "/js/mine.js";
  import { initServerChip } from "/js/chip.js";
  import { initThemesDoc } from "/js/themes-doc.js";

  // One /v1/health for the whole boot: the chip needs it and so does the
  // decision below, so they share the response rather than racing for it.
  let health = null;
  try { health = (await api.health()).body; } catch { health = null; }

  // Fail closed. An unreachable server is not evidence that search is on, and
  // a search form on a page whose server cannot answer is worse than no form.
  // Removed from the document, not hidden: a hidden form still submits on
  // Enter and still starts its status ticker.
  if (!health || health.mining_enabled !== true) {
    document.getElementById("panel-mine")?.remove();
    document.querySelector("nav button[data-panel='mine']")?.remove();
  }

  initPanels(); initExplorer(); initPuzzles(); initMaterials();
  if (health && health.mining_enabled === true) initMine();
  initServerChip(health); initThemesDoc();
</script>
```

- [ ] **Step 6: Move the six search tests onto `server_mining`**

These take `server` today and must take `server_mining`:

```
test_mine_search_and_client_side_validation
test_search_results_are_numbered_and_open_in_the_explorer
test_a_timed_out_search_says_so_instead_of_reporting_no_results
test_the_search_button_becomes_stop_while_in_flight
test_pressing_enter_mid_search_does_not_orphan_the_ticker
test_the_search_rail_matches_the_readout_height
```

Change the fixture parameter and every `server` reference inside each body. Confirm none are missed:

```bash
grep -n "def test_.*(.*server[,)]" src/packages/web/tests/ui/test_dashboard.py | wc -l
taskset -c 0-3 make test-web 2>&1 | tail -20
```

Expected: 95 passed (92 + 3 new).

- [ ] **Step 7: Prove both new guards bite**

Three separate mutations, each restored before the next:

1. Change `?.remove()` on the nav button to `.hidden = true` → `test_search_is_absent_not_hidden_when_mining_is_disabled` must fail on the button count.
2. Restore the hardcoded `["explorer","puzzles","materials","mine","themes"]` in `showPanel` → `test_a_stale_search_deep_link_lands_on_the_explorer` must fail with a page error.
3. Delete the `if (!ids.includes(name))` fallback → the same deep-link test must fail on `#panel-explorer` not being visible.

After each, restore and confirm `git diff` shows only the intended change.

- [ ] **Step 8: Commit**

```bash
git add src/packages/web
git commit -m "$(cat <<'EOF'
feat(web): the dashboard asks the server whether search exists

/v1/health now reports mining_enabled, and the boot script removes
#panel-mine and its nav button from the document when it is false. Removal,
not hiding: round 1 proved a hidden form still submits on Enter and leaves an
orphaned ticker overwriting the status forever.

showPanel's panel list is now derived from the DOM instead of a hardcoded
five-name array. With the array, removing a section made getElementById
return null and .hidden throw -- which would have taken the nav and every
other screen down with it. An unknown panel name now falls back to the
explorer, so a bookmarked #panel=mine lands somewhere real.

Health is fetched once at boot and passed to initServerChip rather than
fetched twice. Failure is closed: an unreachable server is not evidence that
search is on.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: Documentation, version, and the full gate

**Files:**
- Modify: `docs/USAGE.md`, `CHANGELOG.md`, `VERSION`, `pyproject.toml` (root, api, web, cli), `src/packages/api/helpmate_server/__init__.py`, `src/packages/web/helpmate_web/__init__.py`

**Interfaces:**
- Consumes: everything above.
- Produces: version `0.14.0` consistently across the tree — `tests/repo/test_version_consistency.py` enforces it.

- [ ] **Step 1: Find every place the version lives**

```bash
grep -rn "0\.13\.0" --include=pyproject.toml --include=*.py --include=VERSION . \
  | grep -v build/ | grep -v .mypy_cache
```

- [ ] **Step 2: Document the flags in `docs/USAGE.md`**

In the `/v1/mine` section, state plainly that search is off by default, that a disabled server answers **503 `mining_disabled`**, and why the default is off — a scan is not interruptible and is not bounded under concurrent load. Add `mining_disabled` to the error-contract enumerations exactly where `unprobeable_position`, `invalid_theme` and `unknown_material` already appear, and add `mining_enabled` to the documented `/v1/health` response. Document both `--enable-mine` and `--cors-origin` in the `helpmate-server` options list, noting that omitting `--cors-origin` installs no CORS middleware at all.

- [ ] **Step 3: Write the CHANGELOG entry under a `### Changed` heading**

This is a breaking change for anyone already running the server, so it must be prominent rather than a quiet line:

```markdown
## [0.14.0] - 2026-08-13

### Changed
- **Position search (`/v1/mine`) is now off by default** and must be enabled
  with `helpmate-server --enable-mine`. A disabled server answers
  `503 mining_disabled`. A scan cannot be interrupted by `SIGTERM`, its
  timeout is not deterministic under concurrent load, and nothing bounds how
  many run at once — so it is not safe to expose until that work is done. The
  dashboard reads `mining_enabled` from `/v1/health` and omits the Search
  screen entirely when it is off. The CLI `helpmate mine` is unaffected.
- **CORS is opt-in per origin.** `--cors-origin ORIGIN` is repeatable; with
  none given no CORS middleware is installed, where previously every origin
  was allowed. Same-origin use, including the dashboard, is unaffected.

### Added
- `mining_enabled` on `/v1/health`.
```

- [ ] **Step 4: Bump every version to 0.14.0**

Including the `helpmate>=0.13.0,<0.14` dependency pins in `src/packages/api/pyproject.toml` and the CLI's — a `<0.14` ceiling will refuse the new core.

- [ ] **Step 5: Run the full gate**

```bash
taskset -c 0-3 make lint && \
taskset -c 0-3 make jstest && \
taskset -c 0-3 make test-web && \
taskset -c 0-3 python -m pytest tests/repo -v && \
taskset -c 0-3 python -m pytest src/packages/api/tests -v
```

Expected: lint clean, jstest 80, dashboard 95, repo 15, API 112.

- [ ] **Step 6: Verify the shipped default by hand**

Start a server with no flags against a scratch copy of one small table, and confirm both halves:

```bash
d=$(mktemp -d)
cp ~/tb/raw/KQvk.hm ~/tb/raw/KQvk.stats.json ~/tb/raw/Kvk.hm ~/tb/raw/Kvk.stats.json "$d/"
taskset -c 0-3 helpmate-server --tables "$d" --port 8699 &
sleep 3
curl -s "localhost:8699/v1/health" | python3 -m json.tool | grep mining_enabled
curl -s -o /dev/null -w "%{http_code}\n" "localhost:8699/v1/mine?material=KQvk&dtm=4"
curl -s -H "Origin: https://evil.example" -D- -o /dev/null "localhost:8699/v1/health" \
  | grep -i "access-control" || echo "no CORS header — correct"
pkill -f "helpmate[-]server --tables $d"
```

Expected: `"mining_enabled": false`, `503`, `no CORS header — correct`.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "$(cat <<'EOF'
docs: document search-off-by-default and per-origin CORS; bump 0.13.0 -> 0.14.0

Both changes are breaking for anyone already running the server, so the
CHANGELOG carries them under Changed rather than as quiet lines, and USAGE
documents 503 mining_disabled alongside the other error codes rather than
leaving the contract understating its surface.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Self-review

**Spec coverage.** `--enable-mine` and 503 `mining_disabled` → Task 1. `mining_enabled` on `/v1/health` → Task 1. DOM removal rather than hiding, and the single boot health request → Task 3. `--cors-origin` → Task 2. Docs and CHANGELOG → Task 4. The spec's read-only mount, container hardening, hosting and the 30-concurrent `/v1/moves` measurement are **Phase B** and are deliberately absent from this plan; they are not in-repo changes and cannot be built until this ships.

**Not covered here, by design.** The spec's non-goals — fixing `mine`'s concurrency and `SIGTERM` behaviour, deleting search, and moving the dashboard to a private repo — remain untouched.

**Type consistency.** `enable_mine` (Python, snake_case) is the `create_app` parameter and the `--enable-mine` CLI flag; `mining_enabled` (JSON) is the health field read by `index.html`. They differ deliberately: one is a constructor argument, the other a wire field describing state. `initServerChip(health)` takes the body — not the `{body}` envelope `api.health()` returns — and the boot script unwraps it. `cors_origins` is a list on `create_app` and `--cors-origin` is `action="append"`, so argparse supplies a list.
