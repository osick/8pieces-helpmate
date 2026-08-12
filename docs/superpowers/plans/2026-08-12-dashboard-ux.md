# Dashboard UX — Rail and Readout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give all three dashboard panels one skeleton — a grey rail you
manipulate beside a white readout that answers — add drag-and-drop position
editing, per-material statistics under the explorer, a search abort control
and corpus-wide statistics, and fix three defects found measuring against the
full 295-table corpus.

**Architecture:** No build step and no new dependencies. The two surfaces are
semantic CSS aliases over the existing palette (`--rail: var(--ground)`,
`--readout: var(--panel)`), so dark mode comes free. Board editing stays on
the already-vendored cm-chessboard 8.7.5, using events it raises that we
currently ignore. Aggregation happens server-side in a new pure module over
the `.stats.json` sidecars; the rendering layer is extracted from
`materials.js` so the explorer and Materials draw the same charts from the
same code.

**Tech Stack:** Vanilla ES modules served from site-packages, cm-chessboard
8.7.5 (vendored, MIT), FastAPI + Pydantic, pytest, Playwright, `node --test`.

**Spec:** `docs/superpowers/specs/2026-08-12-dashboard-ux-design.md`

## Global Constraints

- **Every build/test command runs under `taskset -c 0-3`.** Never more than 4 cores.
- **Never write to `~/tb` or `~/tb/raw`.** A long 6-piece generation run is live there. Reading is fine. Scratch goes in `$(mktemp -d)`.
- **Never `rm -rf /tmp/tmp.*`** — shared temp dir, wildcard deletes hit other processes.
- **Never let CMake FetchContent clone from GitHub**; prefix pip/build commands with `GIT_CONFIG_GLOBAL=/dev/null`. Never delete `build/_deps`.
- **Never run bare `./build/helpmate_tests`** — always `"~[slow]"` or a specific tag.
- **`ctest` runs without `-j`** — documented shared-temp-dir race in `test_probe.cpp`.
- **No build step, no npm, no bundler, no chessground.** The dashboard serves raw ES modules; nothing is fetched at runtime.
- **No new colours.** Only the tokens already in `css/app.css`. `tests/repo/test_accent_confined_to_focus_and_hover.py` stays in force: every `var(--accent` must sit inside a `:focus-visible` or `:hover` selector.
- **All 28 existing UI tests must stay green.** In particular:
  - `#move-list li` selects exactly move rows — never add an `<li>` inside `#move-list`.
  - Class names `.board-col` and `.side` are asserted; keep them (add `.rail` / `.readout` alongside, do not rename).
  - The 860px breakpoint is asserted on both sides (`gridTemplateColumns` is `none` below, not `none` above).
  - Clicking the armed palette entry a second time still exits edit mode and evaluates.
- **Element IDs must stay unique.** `renderStats` currently hardcodes `#cell-summary`, `#dtm-hist`, `#uniqueness-hist`, `#material-samples`; once it renders on two panels those collide, and `#panel-explorer` comes first in DOM order so the Materials tests would silently query the wrong node.
- **Commit trailer:** `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`
- Shell hazard: `pgrep -f helpmate-server` matches the tool's own command line — use `helpmate[-]server`.
- `for fen in $(...)` shreds FENs on spaces — use `while IFS= read -r`.

## File Structure

**Create**

| File | Responsibility |
|---|---|
| `src/packages/web/helpmate_web/static/js/lib/board-edit.js` | Pure drag helpers: find a square from an event target, decide click-vs-drag. No DOM APIs, no board. |
| `src/packages/web/helpmate_web/static/js/stats-view.js` | DOM rendering of a single material's statistics and of the corpus aggregate. Sibling of `materials.js`, **not** in `lib/` — `lib/` is the node-unit-tested pure layer. |
| `src/packages/api/helpmate_server/aggregate.py` | Pure aggregation over sidecar dicts. No filesystem, no FastAPI. |
| `src/packages/web/tests/js/board-edit.test.js` | node tests for the pure drag helpers. |
| `src/packages/api/tests/test_api_stats.py` | API tests for `/v1/stats` and the aggregation module. |

**Modify**

| File | Change |
|---|---|
| `static/js/lib/stats.js` | `DTM_UNSOLVABLE`, `hasHelpmate`, `mateLengthLabel` |
| `static/js/api.js` | abort signal plumbing, `api.overall()` |
| `static/js/materials.js` | rail filter/grouping/scroll, "All tables", delegate rendering to `stats-view.js` |
| `static/js/explorer.js` | board sizing, drag editing, Done—evaluate, statistics band |
| `static/js/mine.js` | abort, elapsed counter, honest timeout |
| `static/css/app.css` | rail/readout surfaces, board sizing, rail scroll, search rail |
| `static/index.html` | rail/readout markup for all three panels |
| `helpmate_server/app.py` | `material` on probe/moves, `mine_timeout` on health, `GET /v1/stats` |
| `src/packages/web/tests/ui/test_dashboard.py` | new UI tests |
| `README.md`, `docs/USAGE.md`, `CHANGELOG.md`, `VERSION`, 4 × `pyproject.toml`/`__init__.py` | docs + version bump |

---

### Task 1: The `max_dtm` sentinel is guarded, not divided

67 of 295 tables store `max_dtm = 255` (`DTM_UNSOLVABLE`) with an empty
histogram, meaning no helpmate exists in that material. `materials.js` divides
it by two, so `KBvk` currently reads **"longest mate h#127.5"**.

**Files:**
- Modify: `src/packages/web/helpmate_web/static/js/lib/stats.js`
- Modify: `src/packages/web/helpmate_web/static/js/materials.js:56-57`
- Test: `src/packages/web/tests/js/stats.test.js`
- Test: `src/packages/web/tests/ui/test_dashboard.py`

**Interfaces:**
- Produces: `DTM_UNSOLVABLE` (number, 255), `hasHelpmate(stats) -> boolean`, `mateLengthLabel(stats) -> string` — all exported from `js/lib/stats.js`. Tasks 5 and 7 import them.

- [ ] **Step 1: Write the failing test**

Append to `src/packages/web/tests/js/stats.test.js`:

```js
test("a material with no helpmate is named, not divided", () => {
  // KBvk: king and bishop cannot mate. The generator stores the
  // DTM_UNSOLVABLE sentinel as max_dtm and an empty histogram.
  const kbvk = { material: "KBvk", max_dtm: 255, dtm_histogram: { btm: {}, wtm: {} } };
  assert.equal(hasHelpmate(kbvk), false);
  assert.equal(mateLengthLabel(kbvk), "no helpmate exists in this material");
  assert.ok(!mateLengthLabel(kbvk).includes("127.5"));
});

test("a material with a helpmate reports it in h# notation", () => {
  const kqvk = { material: "KQvk", max_dtm: 2, dtm_histogram: { btm: { "2": 9 }, wtm: {} } };
  assert.equal(hasHelpmate(kqvk), true);
  assert.equal(mateLengthLabel(kqvk), "longest mate h#1");
});

test("an odd max_dtm keeps the half step", () => {
  const s = { max_dtm: 33, dtm_histogram: { btm: {}, wtm: { "33": 4 } } };
  assert.equal(mateLengthLabel(s), "longest mate h#16.5");
});

test("the sentinel is recognised even if a histogram is present", () => {
  // Belt and braces: max_dtm is the sentinel and must win regardless.
  const s = { max_dtm: DTM_UNSOLVABLE, dtm_histogram: { btm: { "4": 1 }, wtm: {} } };
  assert.equal(mateLengthLabel(s), "no helpmate exists in this material");
});
```

Extend the existing import at the top of the file to include the three new names:

```js
import {
  dtmBars, uniquenessBuckets, cellSummary, fmtCount,
  DTM_UNSOLVABLE, hasHelpmate, mateLengthLabel,
} from "../../helpmate_web/static/js/lib/stats.js";
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `taskset -c 0-3 make jstest`
Expected: FAIL — `SyntaxError: The requested module ... does not provide an export named 'DTM_UNSOLVABLE'`.

Note: `make jstest` uses node's **spec** reporter, not TAP. A failure is a
`✖` line and a non-zero exit code; do not grep for `not ok`.

- [ ] **Step 3: Implement**

Append to `src/packages/web/helpmate_web/static/js/lib/stats.js`:

```js
// A material where nothing is solvable (KBvk: king and bishop cannot mate)
// stores the DTM_UNSOLVABLE sentinel as max_dtm, not a distance, and an empty
// histogram. Dividing it by two yields "h#127.5" -- a measurement-shaped
// string for a measurement that does not exist. 67 of the 295 tables in the
// reference corpus are in this state, so it is the common case, not an edge.
export const DTM_UNSOLVABLE = 255;

export function hasHelpmate(stats) {
  if (!stats) return false;
  if (Number(stats.max_dtm) >= DTM_UNSOLVABLE) return false;
  const hist = stats.dtm_histogram || {};
  return ["btm", "wtm"].some((side) => Object.keys(hist[side] || {}).length > 0);
}

export function mateLengthLabel(stats) {
  if (!hasHelpmate(stats)) return "no helpmate exists in this material";
  return `longest mate h#${Number(stats.max_dtm) / 2}`;
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `taskset -c 0-3 make jstest`
Expected: PASS, exit 0.

- [ ] **Step 5: Use it in the Materials header**

In `src/packages/web/helpmate_web/static/js/materials.js`, extend the import:

```js
import { dtmBars, uniquenessBuckets, cellSummary, fmtCount, mateLengthLabel } from "./lib/stats.js";
```

and replace lines 56-57:

```js
  head.appendChild(el("span", "sub",
    `${mateLengthLabel(s)} · generated by ${s.generator_version || "unknown"}`));
```

- [ ] **Step 6: Write the UI regression test**

Append to `src/packages/web/tests/ui/test_dashboard.py`:

```python
def test_a_material_with_no_helpmate_says_so(page, server):
    # KBvk: king and bishop cannot mate. The sidecar stores max_dtm = 255,
    # the DTM_UNSOLVABLE sentinel; dividing it by two rendered "h#127.5" for
    # 67 of the 295 tables in the reference corpus.
    page.goto(f"{server}/#panel=materials")
    page.wait_for_function("window.__materialsReady === true")
    page.click("#material-list li[data-material=Kvk]")
    page.wait_for_selector("#material-stats .stats-head")
    sub = page.inner_text("#material-stats .stats-head")
    assert "no helpmate exists" in sub
    assert "127.5" not in sub
    assert "h#" not in sub.split("·")[0]
```

`Kvk` (bare kings) is in the UI fixture's generated closure and has no
helpmate, so it exercises the same branch as `KBvk` without needing the
295-table corpus.

- [ ] **Step 7: Run the UI test**

Run: `taskset -c 0-3 make test-web`
Expected: 29 passed. `test-web` reinstalls `helpmate_web` first — the UI
fixture serves the **installed** package, so a source-only edit is invisible
to it.

- [ ] **Step 8: Commit**

```bash
git add src/packages/web/helpmate_web/static/js/lib/stats.js \
        src/packages/web/helpmate_web/static/js/materials.js \
        src/packages/web/tests/js/stats.test.js \
        src/packages/web/tests/ui/test_dashboard.py
git commit -m "fix(web): name the materials that have no helpmate

67 of 295 tables store max_dtm = DTM_UNSOLVABLE and an empty histogram.
Dividing that by two rendered 'longest mate h#127.5' for KBvk, KNvk and
65 others -- a measurement-shaped string for a measurement that does not
exist.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: The API names the table that answered

The explorer must show statistics for the table that actually answered, and
`/v1/probe` answers colour-flipped positions from the *mirrored* material.
Deriving it client-side from the FEN would be wrong exactly when it matters.

**Files:**
- Modify: `src/packages/api/helpmate_server/app.py:114-119` (health), `:154-229` (probe), `:248-275` (moves)
- Test: `src/packages/api/tests/test_api_probe.py`, `test_api_moves.py`, `test_api_catalog.py`

**Interfaces:**
- Produces: `/v1/probe` and `/v1/moves` responses gain `"material": str` — the material whose table answered, mirrored when `flipped` is true. `/v1/health` gains `"mine_timeout": float`. Tasks 6 and 8 consume these.

- [ ] **Step 1: Write the failing tests**

Append to `src/packages/api/tests/test_api_probe.py`:

```python
def test_probe_names_the_table_that_answered(client):
    r = client.get("/v1/probe", params={"fen": "8/7k/5K2/8/8/8/8/6Q1 b - - 0 1"})
    assert r.status_code == 200
    assert r.json()["material"] == "KQvk"


def test_probe_names_the_mirrored_table_when_colors_were_flipped(client):
    # Black holds the queen, so the position's own material is Kvkq and only
    # KQvk exists. probe() answers by flipping; the material it reports must
    # be the table that did the work, not the one the FEN spells out.
    r = client.get("/v1/probe", params={"fen": "8/7K/5k2/8/8/8/8/6q1 w - - 0 1"})
    assert r.status_code == 200
    body = r.json()
    assert body["flipped"] is True
    assert body["material"] == "KQvk"
```

Append to `src/packages/api/tests/test_api_moves.py`:

```python
def test_moves_names_the_table_that_answered(client):
    r = client.get("/v1/moves", params={"fen": "8/7k/5K2/8/8/8/8/6Q1 b - - 0 1"})
    assert r.status_code == 200
    assert r.json()["material"] == "KQvk"
```

Append to `src/packages/api/tests/test_api_catalog.py`:

```python
def test_health_reports_the_mine_timeout_budget(client):
    # The search screen counts up against this budget, so it must not be a
    # number hardcoded in JavaScript.
    body = client.get("/v1/health").json()
    assert body["mine_timeout"] == 30.0
```

- [ ] **Step 2: Run to verify they fail**

Run: `taskset -c 0-3 python -m pytest src/packages/api/tests/test_api_probe.py src/packages/api/tests/test_api_moves.py src/packages/api/tests/test_api_catalog.py -v`
Expected: 4 failures — `KeyError: 'material'` and `KeyError: 'mine_timeout'`.

- [ ] **Step 3: Implement in `app.py`**

In `health()` (line 116), add the budget to the returned dict:

```python
        return {"status": "ok", "version": __version__,
                "mine_timeout": mine_timeout,
                "tables_local": sum(1 for s in cat if s.location in ("local", "cached")),
                "tables_remote": sum(1 for s in cat if s.location == "remote")}
```

In `probe()`, replace the `out` construction (line 175-176) with:

```python
        dtm, count, flipped = res
        # The table that DID THE WORK, which is the mirrored material whenever
        # the C++ layer answered by flipping colours. Deriving this client-side
        # from the FEN would be wrong in exactly the case that matters.
        out = {"dtm": dtm, "count": count, "flipped": flipped,
               "material": flipped_mat if flipped else material,
               "notation": h_notation(dtm)}
```

and the unsolvable branch above it (line 172-173):

```python
        if res is None:
            return {"solvable": False, "material": material}
```

In `moves()`, replace the two return statements (lines 271-275):

```python
        if res is None:
            return {"fen": fen, "solvable": False, "material": material, "moves": out}
        dtm, count, flip = res
        return {"fen": fen, "dtm": dtm, "count": count, "notation": h_notation(dtm),
                "flipped": flip, "material": flipped if flip else material,
                "moves": out}
```

Note the local name collision: inside `moves()` the mirrored material is
already bound to `flipped` (line 253) and the flip *flag* is `flip`. Do not
rename either — just read them in the right order.

- [ ] **Step 4: Run to verify they pass**

Run: `taskset -c 0-3 python -m pytest src/packages/api/tests -v`
Expected: all pass, including the pre-existing probe/moves tests.

- [ ] **Step 5: Typecheck and lint**

Run: `taskset -c 0-3 make typecheck && taskset -c 0-3 make lint`
Expected: both clean. mypy covers `src/packages/api/helpmate_server` only, so
`app.py` is in scope.

- [ ] **Step 6: Commit**

```bash
git add src/packages/api/helpmate_server/app.py src/packages/api/tests/
git commit -m "feat(api): report the answering table and the mine budget

/v1/probe and /v1/moves gain a material field naming the table that
answered -- the mirrored one when the C++ layer flipped colours, which a
client deriving it from the FEN would get wrong exactly when it matters.
/v1/health reports mine_timeout so the search screen's countdown is the
server's real budget rather than a number hardcoded in JavaScript.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: `GET /v1/stats` — the corpus aggregate

**Files:**
- Create: `src/packages/api/helpmate_server/aggregate.py`
- Create: `src/packages/api/tests/test_api_stats.py`
- Modify: `src/packages/api/helpmate_server/app.py` (new route, after `stats`)

**Interfaces:**
- Produces: `aggregate_stats(sidecars: list[dict], catalog: list[SliceInfo]) -> dict` in `helpmate_server.aggregate`; `GET /v1/stats`. Task 7 consumes the endpoint.
- Consumes: `SliceInfo` from `helpmate_server.storage` (fields: `material`, `pieces`, `size_bytes`, `max_dtm`, `cells`, `location`).

- [ ] **Step 1: Write the failing tests**

Create `src/packages/api/tests/test_api_stats.py`:

```python
"""Why this exists: the Materials screen's landing state summarises every
table at once, and the two facts most easily got wrong in a summary are the
ones a mixed corpus makes uncomfortable -- that 67 of 295 tables contain no
helpmate at all, and that seven different generator versions produced the
rest. A summary that quietly drops either is not shorter, it is wrong."""

from helpmate_server.aggregate import aggregate_stats
from helpmate_server.storage import SliceInfo


def _slice(material, pieces, size, location="local"):
    return SliceInfo(material, pieces, size, None, None, location)


KQVK = {
    "material": "KQvk", "max_dtm": 2, "plane_size": 100,
    "generator_version": "0.9.1",
    "cells": {"invalid": {"btm": 10, "wtm": 20}, "unsolvable": {"btm": 5, "wtm": 5}},
    "dtm_histogram": {"btm": {"2": 40}, "wtm": {"1": 60}},
    "uniqueness": {"btm": {"2": {"1": 30, "3": 10}}, "wtm": {"1": {"1": 60}}},
}
KBVK = {
    "material": "KBvk", "max_dtm": 255, "plane_size": 50,
    "generator_version": "0.6.1",
    "cells": {"invalid": {"btm": 30, "wtm": 40}, "unsolvable": {"btm": 20, "wtm": 10}},
    "dtm_histogram": {"btm": {}, "wtm": {}},
    "uniqueness": {"btm": {}, "wtm": {}},
}


def test_a_table_with_no_helpmate_is_named_not_ranked():
    agg = aggregate_stats([KQVK, KBVK],
                          [_slice("KQvk", 3, 700), _slice("KBvk", 3, 300)])
    assert agg["no_helpmate"] == ["KBvk"]
    assert agg["max_dtm"] == 2
    assert [d["material"] for d in agg["deepest"]] == ["KQvk"]


def test_sums_are_over_every_table():
    agg = aggregate_stats([KQVK, KBVK],
                          [_slice("KQvk", 3, 700), _slice("KBvk", 3, 300)])
    assert agg["tables"] == 2
    assert agg["size_bytes"] == 1000
    assert agg["tables_by_pieces"] == {"3": 2}
    # total = plane_size * 2 per table: (100 + 50) * 2
    assert agg["cells"]["total"] == 300
    assert agg["cells"]["invalid"] == 100      # 10+20+30+40
    assert agg["cells"]["unsolvable"] == 40    # 5+5+20+10
    assert agg["cells"]["solvable"] == 160
    assert agg["dtm_histogram"]["btm"] == {"2": 40}
    assert agg["dtm_histogram"]["wtm"] == {"1": 60}
    assert agg["generators"] == {"0.9.1": 1, "0.6.1": 1}


def test_uniqueness_is_collapsed_over_distance_under_one_key():
    # The per-distance breakdown does not survive aggregation -- the client
    # buckets over every distance anyway -- but the SHAPE must survive, so
    # lib/stats.js uniquenessBuckets() reads the aggregate unchanged.
    agg = aggregate_stats([KQVK], [_slice("KQvk", 3, 700)])
    assert list(agg["uniqueness"]["btm"]) == ["all"]
    assert agg["uniqueness"]["btm"]["all"] == {"1": 30, "3": 10}


def test_a_table_without_a_sidecar_is_counted_and_declared():
    # A remote-only table has no local sidecar. Counting it in `tables` while
    # excluding it from the sums under-reports silently unless we say so.
    agg = aggregate_stats([KQVK],
                          [_slice("KQvk", 3, 700), _slice("KRvkq", 4, 0, "remote")])
    assert agg["tables"] == 2
    assert agg["tables_without_stats"] == 1
    assert agg["tables_by_pieces"] == {"3": 1, "4": 1}


def test_the_endpoint_serves_the_aggregate(client):
    body = client.get("/v1/stats").json()
    assert body["tables"] >= 1
    assert "KQvk" in [d["material"] for d in body["deepest"]]
    assert body["cells"]["total"] > 0


def test_the_aggregate_is_recomputed_when_a_table_appears(kqvk_dir, tmp_path):
    # The cache is keyed on the catalog, so a newly generated or downloaded
    # table must invalidate it -- and nothing else may.
    from fastapi.testclient import TestClient
    from helpmate_server.storage import LocalDir, ChainSource
    from helpmate_server.app import create_app

    for ext in (".hm", ".stats.json"):
        (tmp_path / f"KQvk{ext}").write_bytes((kqvk_dir / f"KQvk{ext}").read_bytes())
    c = TestClient(create_app(ChainSource([LocalDir(tmp_path)])))

    first = c.get("/v1/stats").json()
    assert first["tables"] == 1
    assert c.get("/v1/stats").json() == first          # served from cache

    for ext in (".hm", ".stats.json"):
        (tmp_path / f"Kvk{ext}").write_bytes((kqvk_dir / f"Kvk{ext}").read_bytes())
    second = c.get("/v1/stats").json()
    assert second["tables"] == 2, "the catalog changed and the cache did not"
    assert second["no_helpmate"] == ["Kvk"]            # bare kings cannot mate
```

- [ ] **Step 2: Run to verify they fail**

Run: `taskset -c 0-3 python -m pytest src/packages/api/tests/test_api_stats.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'helpmate_server.aggregate'`.

- [ ] **Step 3: Write `aggregate.py`**

Create `src/packages/api/helpmate_server/aggregate.py`:

```python
"""Corpus-wide summary over the .stats.json sidecars.

Pure: it takes already-parsed sidecar dicts and a catalog, and touches
neither the filesystem nor FastAPI, so the awkward cases -- a material with
no helpmate, a remote table with no sidecar -- are unit-testable without
generating a table.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Iterable, Sequence

from .storage import SliceInfo

# A material where nothing is solvable stores this sentinel as max_dtm, not a
# distance. 67 of the 295 tables in the reference corpus are in that state.
DTM_UNSOLVABLE = 255

# How many entries the "deepest tables" ranking carries.
DEEPEST_N = 10


def has_helpmate(sidecar: dict[str, Any]) -> bool:
    if int(sidecar.get("max_dtm", DTM_UNSOLVABLE)) >= DTM_UNSOLVABLE:
        return False
    hist = sidecar.get("dtm_histogram") or {}
    return any(hist.get(side) for side in ("btm", "wtm"))


def aggregate_stats(sidecars: Sequence[dict[str, Any]],
                    catalog: Iterable[SliceInfo]) -> dict[str, Any]:
    cat = list(catalog)
    by_pieces: Counter[str] = Counter(str(s.pieces) for s in cat)
    generators: Counter[str] = Counter()
    dtm: dict[str, Counter[str]] = {"btm": Counter(), "wtm": Counter()}
    uniq: dict[str, Counter[str]] = {"btm": Counter(), "wtm": Counter()}
    totals: defaultdict[str, int] = defaultdict(int)
    no_helpmate: list[str] = []
    deepest: list[dict[str, Any]] = []

    for s in sidecars:
        generators[s.get("generator_version") or "unknown"] += 1
        totals["total"] += int(s.get("plane_size") or 0) * 2
        cells = s.get("cells") or {}
        for kind in ("invalid", "unsolvable"):
            side_counts = cells.get(kind) or {}
            totals[kind] += int(side_counts.get("btm") or 0)
            totals[kind] += int(side_counts.get("wtm") or 0)

        if not has_helpmate(s):
            no_helpmate.append(str(s.get("material") or "unknown"))
            continue

        deepest.append({"material": s.get("material"), "max_dtm": int(s["max_dtm"])})
        hist = s.get("dtm_histogram") or {}
        for side in ("btm", "wtm"):
            for key, n in (hist.get(side) or {}).items():
                dtm[side][key] += int(n)
            # The per-distance breakdown does not survive aggregation; the
            # client buckets over every distance anyway. Collapsing under one
            # synthetic key keeps the nested SHAPE the reader expects.
            for per_dtm in (s.get("uniqueness") or {}).get(side, {}).values():
                for key, n in (per_dtm or {}).items():
                    uniq[side][key] += int(n)

    totals["solvable"] = totals["total"] - totals["invalid"] - totals["unsolvable"]
    deepest.sort(key=lambda d: (-d["max_dtm"], str(d["material"])))

    return {
        "tables": len(cat),
        "tables_by_pieces": dict(sorted(by_pieces.items())),
        "tables_without_stats": len(cat) - len(sidecars),
        "size_bytes": sum(s.size_bytes for s in cat),
        "cells": {k: totals[k] for k in ("solvable", "unsolvable", "invalid", "total")},
        "dtm_histogram": {side: dict(dtm[side]) for side in ("btm", "wtm")},
        "uniqueness": {side: ({"all": dict(uniq[side])} if uniq[side] else {})
                       for side in ("btm", "wtm")},
        "max_dtm": deepest[0]["max_dtm"] if deepest else None,
        "deepest": deepest[:DEEPEST_N],
        "no_helpmate": sorted(no_helpmate),
        "generators": dict(generators),
    }
```

- [ ] **Step 4: Add the route to `app.py`**

`app.py` does not currently import `json` — it imports only `re`, `Path` and
`Optional`. Add `import json` beside `import re`.

Insert this immediately after the `stats(name)` route (after line 136):

```python
    # Recomputing this walks every sidecar (295 files / 13 MB / 0.17s to parse
    # on the reference corpus), so it is cached against a signature of the
    # catalog itself: a newly generated or downloaded table invalidates it and
    # nothing else does. Closure state, not module state, so each create_app()
    # in the test suite starts cold.
    agg_cache: dict[str, object] = {}

    @app.get("/v1/stats")
    def stats_overall():
        cat = chain.catalog()
        key = tuple(sorted((s.material, s.size_bytes, s.location) for s in cat))
        if agg_cache.get("key") == key:
            return agg_cache["value"]
        sidecars = []
        for s in cat:
            d = chain.resolve(s.material)
            if d is None:
                continue
            p = Path(d) / f"{s.material}.stats.json"
            if not p.exists():
                continue
            try:
                sidecars.append(json.loads(p.read_text()))
            except (OSError, ValueError):
                # A truncated sidecar (an interrupted generation run) must not
                # take the whole summary down; it counts as "without stats".
                continue
        value = aggregate_stats(sidecars, cat)
        agg_cache["key"] = key
        agg_cache["value"] = value
        return value
```

and add the import beside the storage import at the top:

```python
from .aggregate import aggregate_stats
```

- [ ] **Step 5: Run the tests**

Run: `taskset -c 0-3 python -m pytest src/packages/api/tests -v`
Expected: all pass.

- [ ] **Step 6: Verify against the real corpus**

The unit tests use two hand-built sidecars. Confirm the endpoint holds up on
295 real ones — read-only, `~/tb` is never written:

```bash
taskset -c 0-3 python -c "
from fastapi.testclient import TestClient
from helpmate_server.storage import LocalDir, ChainSource
from helpmate_server.app import create_app
import time
c = TestClient(create_app(ChainSource([LocalDir('/home/os/tb')])))
t = time.time(); b = c.get('/v1/stats').json(); cold = time.time() - t
t = time.time(); c.get('/v1/stats'); warm = time.time() - t
print(f'cold {cold:.2f}s  warm {warm:.4f}s')
print('tables', b['tables'], 'by pieces', b['tables_by_pieces'])
print('no_helpmate', len(b['no_helpmate']), 'max_dtm', b['max_dtm'])
print('deepest', b['deepest'][:3])
print('generators', b['generators'])
"
```

Expected, measured on this corpus: 295 tables;
`{"2":1,"3":10,"4":55,"5":220,"6":9}` (the repo's `_piece_count` counts every
character except the `v` separator, so `Kvk` is two pieces); 67 with no
helpmate; `max_dtm` 34; deepest `KBvkqp` (34), `KBvkrp` (33), then a three-way
tie at 32 broken alphabetically so `KBBvkp` comes third; seven generator
versions with `0.8.0` at 159. Warm must be far below cold — that is the cache.
**Record this output in the task report.**

- [ ] **Step 7: Lint and typecheck**

Run: `taskset -c 0-3 make lint && taskset -c 0-3 make typecheck`
Expected: clean.

- [ ] **Step 8: Commit**

```bash
git add src/packages/api/helpmate_server/aggregate.py \
        src/packages/api/helpmate_server/app.py \
        src/packages/api/tests/test_api_stats.py
git commit -m "feat(api): GET /v1/stats, the corpus-wide aggregate

Sums every sidecar into one summary for the Materials landing state.
Aggregation is a pure function over parsed sidecars, so the awkward cases
-- a material with no helpmate, a remote table with no sidecar -- are
testable without generating a table.

Cached against a signature of the catalog, because recomputing walks 295
files (13 MB, 0.17s to parse on the reference corpus).

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Rail and readout, and the board that overflowed

Measured: at a 960px viewport the board is 460px wide inside a 368px grid
column, its right edge 66px past the move list's left edge, landing on top of
the first move's SAN and the FEN field. Two different sizing rules for one
box; this replaces them with one.

**Files:**
- Modify: `src/packages/web/helpmate_web/static/css/app.css:36-79` (tokens), `:181-231` (explorer)
- Modify: `src/packages/web/helpmate_web/static/index.html:41-108`
- Test: `src/packages/web/tests/ui/test_dashboard.py`

**Interfaces:**
- Produces: CSS classes `.rail` and `.readout`, tokens `--rail` / `--readout`. Tasks 7 and 8 apply them to the Materials and Search panels.

- [ ] **Step 1: Write the failing tests**

Append to `src/packages/web/tests/ui/test_dashboard.py`:

```python
import pytest


@pytest.mark.parametrize("width", [880, 960, 1024, 1280])
def test_the_board_never_overlaps_the_readout(page, server, width):
    # Regression, measured before the fix: #board was min(88vw, 460px) while
    # its grid column was min(460px, 40%). At 960px that put a 460px board in
    # a 368px column, 66px of it lying on top of the move list.
    page.set_viewport_size({"width": width, "height": 1000})
    page.goto(server)
    page.wait_for_selector("#move-list li")
    board = page.eval_on_selector("#board", "e => e.getBoundingClientRect()")
    side = page.eval_on_selector(".side", "e => e.getBoundingClientRect()")
    assert board["right"] <= side["left"] + 1, (
        f"board overlaps the readout by {board['right'] - side['left']:.0f}px at {width}px")


@pytest.mark.parametrize("width", [880, 1280])
def test_the_board_is_centred_in_its_rail(page, server, width):
    page.set_viewport_size({"width": width, "height": 1000})
    page.goto(server)
    page.wait_for_selector("#move-list li")
    board = page.eval_on_selector("#board", "e => e.getBoundingClientRect()")
    rail = page.eval_on_selector(".board-col", "e => e.getBoundingClientRect()")
    left = board["left"] - rail["left"]
    right = rail["right"] - board["right"]
    assert abs(left - right) <= 1, f"board off-centre by {abs(left - right):.1f}px"


def test_the_rail_and_the_readout_are_different_surfaces(page, server):
    page.set_viewport_size({"width": 1280, "height": 1000})
    page.goto(server)
    page.wait_for_selector("#move-list li")
    rail = page.eval_on_selector(".board-col", "e => getComputedStyle(e).backgroundColor")
    readout = page.eval_on_selector(".side", "e => getComputedStyle(e).backgroundColor")
    assert rail != readout, "rail and readout render on the same surface"
    assert rail not in ("rgba(0, 0, 0, 0)", "transparent")
    assert readout not in ("rgba(0, 0, 0, 0)", "transparent")


def test_the_board_stays_put_while_the_readout_scrolls(page, server):
    # The rail is sticky. `overflow: hidden` on any ancestor would create a
    # scroll container and silently kill that -- an easy thing to add while
    # clipping surfaces to a border radius, and invisible to every other test.
    page.set_viewport_size({"width": 1280, "height": 700})
    page.goto(f"{server}/#fen={quote(THREE_GROUPS)}")
    page.wait_for_selector("#move-list li")
    before = page.eval_on_selector("#board", "e => e.getBoundingClientRect().top")
    page.evaluate("window.scrollBy(0, 400)")
    page.wait_for_timeout(100)
    after = page.eval_on_selector("#board", "e => e.getBoundingClientRect().top")
    assert after > before - 400 + 50, "the board scrolled away instead of sticking"
    assert after >= -1, "the board is above the viewport"
```

`THREE_GROUPS` already exists in this file; `quote` is already imported.

- [ ] **Step 2: Run to verify they fail**

Run: `taskset -c 0-3 make test-web`
Expected: `test_the_board_never_overlaps_the_readout[960]` and `[880]` FAIL
with the overlap message; the surface test FAILs (both columns transparent);
the centring test FAILs.

**Record the exact overlap figures in the task report** — the point of this
task is that they go to zero, and a test that has never been seen to fail is
not evidence.

- [ ] **Step 3: Add the surface tokens**

In `css/app.css`, inside the bare `:root` block (after `--r: 6px;`, line 75):

```css
  /* Grey is what you manipulate, white is what the tables say. Aliases, not
     new values: --panel (#262421) sits ABOVE --ground (#161512) in dark mode,
     so the rail recedes and the readout advances in BOTH themes rather than
     inverting. Defining them here and nowhere else means the dark blocks
     below need no counterpart. */
  --rail: var(--ground);
  --readout: var(--panel);
```

Do **not** add them to the two dark blocks — they are aliases, and the tokens
they point at are already redefined there.

- [ ] **Step 4: Replace the explorer layout**

In `css/app.css`, replace the whole `/* ---------- explorer ---------- */`
block from line 181 through line 203 (up to and including the closing brace of
the `@media (min-width: 860px)` block) with:

```css
/* ---------- rail and readout ---------- */

/* One card per panel, split into a rail and a readout. No `overflow: hidden`
   anywhere on this path: it would create a scroll container and silently
   cancel the rail's `position: sticky`. */
#panel-explorer, #panel-materials, #panel-mine {
  border: 1px solid var(--rule); border-radius: var(--r);
  background: var(--readout);
}
.rail { background: var(--rail); padding: var(--s3); border-radius: var(--r) var(--r) 0 0; }
.readout { padding: var(--s3); }

@media (min-width: 860px) {
  .rail { border-radius: var(--r) 0 0 var(--r); }
  .readout { border-left: 1px solid var(--rule); }
}

/* ---------- explorer ---------- */

/* Mobile is the default; two columns are the enhancement. The rail's maximum
   is the board's maximum, so the board can size itself from its column
   instead of from the viewport -- one rule, and the overlap that two rules
   produced between 860px and ~1150px is impossible by construction. */
#panel-explorer { display: flex; flex-direction: column; }
.board-col { display: flex; flex-direction: column; gap: var(--s3); }
#board { width: 100%; max-width: 460px; margin-inline: auto; aspect-ratio: 1; }
.side { display: flex; flex-direction: column; gap: var(--s4); min-width: 0; }
.side > * { margin: 0; }

@media (min-width: 860px) {
  #panel-explorer {
    display: grid;
    grid-template-columns: minmax(300px, 460px) minmax(320px, 1fr);
    align-items: start;
  }
  /* The rail stays put and only the readout scrolls, so a long move list
     never drags the board out of view. No sticky headers, no scroll-sync JS. */
  .board-col { position: sticky; top: var(--s3); }
}
```

Note what changed beyond the sizing: the `gap` is gone from both the flex and
the grid, because the two surfaces now meet at a rule instead of floating
apart, and the padding lives on `.rail` / `.readout`.

- [ ] **Step 5: Take the card borders off what is now on a surface**

Still in `css/app.css`, replace the `.palette` rule (line 205-210) with:

```css
.palette {
  display: flex; flex-direction: column; gap: var(--s2);
  border-top: 1px solid var(--rule); padding-top: var(--s3);
  width: 100%; max-width: 460px; margin-inline: auto;
}
```

The palette is on the rail now; a border and a fill around it drew a card
inside a surface. A rule separates it from the board instead.

And make the readout's tiles legible against the readout, replacing the
`.tile` rule (line 324-327):

```css
/* On the readout these sit on --panel, so a --panel fill would leave them
   invisible except for their rule. Fill from --sunk and drop the border. */
.tile {
  border-radius: var(--r); background: var(--sunk);
  padding: .45rem .7rem; min-width: 8.5rem;
}
```

- [ ] **Step 6: Apply the classes in `index.html`**

In `src/packages/web/helpmate_web/static/index.html`, line 42:

```html
    <div class="rail board-col">
```

and line 60:

```html
    <div class="readout side">
```

Keep `.board-col` and `.side` — six existing tests select on them.

- [ ] **Step 7: Run the tests**

Run: `taskset -c 0-3 make test-web`
Expected: all pass, including the four pre-existing layout tests
(`test_below_the_breakpoint_the_columns_stack_and_nothing_is_hidden` asserts
`gridTemplateColumns == "none"` below 860px and a sibling asserts it is not
`none` above — the breakpoint has not moved).

- [ ] **Step 8: Look at it**

Screenshots are not optional here: the last cycle's single worst defect was
an invisible control under a fully green suite.

```bash
taskset -c 0-3 python - <<'PY'
import asyncio
from playwright.async_api import async_playwright
OUT = "/tmp/claude-1000/.../scratchpad"   # use this session's scratchpad
async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(args=["--no-sandbox"])
        for theme in ("light", "dark"):
            for w in (880, 960, 1280):
                pg = await b.new_page(viewport={"width": w, "height": 1000},
                                      color_scheme=theme)
                await pg.goto("http://127.0.0.1:8642/", wait_until="networkidle")
                await pg.wait_for_selector("#move-list li")
                await pg.screenshot(path=f"{OUT}/t4-{theme}-{w}.png", full_page=True)
                await pg.close()
        await b.close()
asyncio.run(main())
PY
```

Check by eye: the rail and readout meet cleanly at the rule, the board is
centred, the palette reads as part of the rail rather than a card on it, and
the dark theme's rail is *darker* than its readout. Attach the six images to
the task report.

- [ ] **Step 9: Commit**

```bash
git add src/packages/web/helpmate_web/static/css/app.css \
        src/packages/web/helpmate_web/static/index.html \
        src/packages/web/tests/ui/test_dashboard.py
git commit -m "feat(web): rail and readout, and one sizing rule for the board

Grey is what you manipulate, white is what the tables say. The two
surfaces are aliases over the existing palette, so dark mode needs no
counterpart and no new colour enters the file.

Fixes the overlap: #board was min(88vw, 460px) inside a min(460px, 40%)
column, so between 860px and ~1150px the board lay on top of the move
list -- 66px of it at 960px, measured. The rail's maximum is now the
board's maximum and the board sizes from its column, so the two rules
that had to agree became one.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Extract the statistics renderer

Pure refactor, no behaviour change. It must land on its own so the review
that follows has nothing else to look at.

**Files:**
- Create: `src/packages/web/helpmate_web/static/js/stats-view.js`
- Modify: `src/packages/web/helpmate_web/static/js/materials.js`

**Interfaces:**
- Produces: `renderStats(box, stats, { idPrefix = "", samples = true } = {})` and `renderAggregate(box, agg)` from `js/stats-view.js`. Tasks 6 and 7 consume both.

- [ ] **Step 1: Create `stats-view.js`**

Move `fmtSize`, `el`, `tile`, `histogram`, `chart` and `renderStats` out of
`materials.js` verbatim, with one change: the hardcoded element IDs take a
prefix. Create `src/packages/web/helpmate_web/static/js/stats-view.js`:

```js
// How a material's statistics are drawn. Shared by the Materials panel and
// the explorer's per-table band, so the two never drift.
//
// idPrefix exists because these ids were unique only while one panel drew
// them. #panel-explorer precedes #panel-materials in the document, so an
// unprefixed second copy would not merely duplicate an id -- it would make
// every existing `#dtm-hist` query resolve to the explorer's chart.
import { encodeState } from "./lib/state.js";
import { dtmBars, uniquenessBuckets, cellSummary, fmtCount, mateLengthLabel } from "./lib/stats.js";

export function fmtSize(n) {
  if (n >= 1e9) return `${(n / 1e9).toFixed(2)} GB`;
  if (n >= 1e6) return `${(n / 1e6).toFixed(1)} MB`;
  if (n >= 1e3) return `${(n / 1e3).toFixed(1)} kB`;
  return `${n} B`;
}

export const el = (tag, cls, text) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined) n.textContent = text;
  return n;
};

export function tile(parent, key, value) {
  const t = el("div", "tile");
  t.appendChild(el("span", "k", key));
  t.appendChild(el("span", "v", value));
  parent.appendChild(t);
}

// A histogram row is key / bar / value, laid out by the .hist grid.
export function histogram(rows, { barClass } = {}) {
  const box = el("div", "hist");
  for (const r of rows) {
    const k = el("span", "k", r.label);
    const bar = el("span", `bar${barClass ? ` ${barClass(r)}` : ""}`);
    const fill = el("i");
    fill.style.width = `${(r.share * 100).toFixed(2)}%`;
    bar.appendChild(fill);
    const v = el("span", "v", fmtCount(r.positions));
    box.append(k, bar, v);
  }
  box.dataset.rows = String(rows.length);
  return box;
}

export function chart(title, hint, node, id) {
  const c = el("div", "chart");
  if (id) c.id = id;
  c.appendChild(el("span", "eyebrow", title));
  c.appendChild(el("p", "hint", hint));
  c.appendChild(node);
  return c;
}

function dtmChart(box, s, idPrefix) {
  const bars = dtmBars(s);
  if (!bars.length) return;
  const h = histogram(bars, { barClass: (r) => r.side });
  h.id = `${idPrefix}dtm-hist`;
  const c = chart("Mate length", "How many positions mate in each distance, over both sides to move.", h);
  const legend = el("div", "chart-legend");
  const a = el("span"); a.append(el("i"), document.createTextNode("Black to move"));
  const b = el("span"); b.append(el("i", "wtm"), document.createTextNode("White to move"));
  legend.append(a, b);
  c.appendChild(legend);
  box.appendChild(c);
}

function uniquenessChart(box, s, idPrefix) {
  const uniq = uniquenessBuckets(s);
  if (!uniq.length) return;
  const h = histogram(uniq);
  h.id = `${idPrefix}uniqueness-hist`;
  box.appendChild(chart("Solutions per position",
    "How many distinct optimal lines those positions have. One is a sound problem; the counter saturates at 255.",
    h));
}

export function renderStats(box, s, { idPrefix = "", samples = true } = {}) {
  box.textContent = "";

  const head = el("div", "stats-head");
  head.appendChild(el("h2", null, s.material));
  head.appendChild(el("span", "sub",
    `${mateLengthLabel(s)} · generated by ${s.generator_version || "unknown"}`));
  box.appendChild(head);

  const cells = cellSummary(s);
  const tiles = el("div", "tiles");
  tiles.id = `${idPrefix}cell-summary`;
  tile(tiles, "solvable", fmtCount(cells.solvable));
  tile(tiles, "no mate", fmtCount(cells.unsolvable));
  tile(tiles, "illegal", fmtCount(cells.invalid));
  tile(tiles, "cells total", fmtCount(cells.total));
  box.appendChild(tiles);

  dtmChart(box, s, idPrefix);
  uniquenessChart(box, s, idPrefix);

  if (!samples) return;
  const list = el("ul", null);
  list.id = `${idPrefix}material-samples`;
  const seen = new Set();
  for (const fen of (s.deepest || []).concat(s.deepest_unique || [])) {
    if (seen.has(fen)) continue;
    seen.add(fen);
    const li = el("li", null, fen);
    li.addEventListener("click", () => { location.hash = encodeState({ fen, panel: "explorer" }); });
    list.appendChild(li);
  }
  if (!list.children.length) return;
  const c = el("div", "chart");
  c.appendChild(el("span", "eyebrow", "Sample positions"));
  c.appendChild(el("p", "hint", "The deepest positions in this table, and the deepest with a single solution. Click one to open it."));
  c.appendChild(list);
  box.appendChild(c);
}
```

- [ ] **Step 2: Reduce `materials.js` to the panel's own job**

Replace lines 1-108 of `src/packages/web/helpmate_web/static/js/materials.js`
with:

```js
import { api, ApiError, DOWNLOAD_RETRY_CAP, DOWNLOAD_RETRY_MS } from "./api.js";
import { fmtSize, el, renderStats } from "./stats-view.js";
```

and delete the now-duplicated `fmtSize`, `el`, `tile`, `histogram`, `chart`
and `renderStats` definitions. Keep `showStats` and `initMaterials` exactly as
they are; `renderStats(box, res.body)` still calls with the default
`idPrefix: ""`, so every existing id is unchanged.

`encodeState` is still used by `initMaterials`? No — it was used only by the
sample list, which moved. Remove the `encodeState` import from `materials.js`
if nothing else references it; `make lint`'s `node --check` will not catch an
unused import, so grep before deleting:

```bash
grep -n "encodeState\|dtmBars\|uniquenessBuckets\|cellSummary\|fmtCount" \
  src/packages/web/helpmate_web/static/js/materials.js
```

- [ ] **Step 3: Verify nothing changed**

Run: `taskset -c 0-3 make test-web`
Expected: all pass, unchanged — this is a refactor, so a *new* failure means
the extraction was not faithful.

- [ ] **Step 4: Prove the ids are still what the tests select**

```bash
taskset -c 0-3 python -c "
from playwright.sync_api import sync_playwright
with sync_playwright() as pw:
    b = pw.chromium.launch(args=['--no-sandbox']); pg = b.new_page()
    pg.goto('http://127.0.0.1:8642/#panel=materials')
    pg.wait_for_function('window.__materialsReady === true')
    pg.click('#material-list li[data-material=KQvk]')
    pg.wait_for_selector('#dtm-hist')
    for sel in ('#cell-summary', '#dtm-hist', '#uniqueness-hist', '#material-samples'):
        n = pg.eval_on_selector_all(sel, 'e => e.length')
        print(sel, n); assert n == 1, sel
    b.close()
print('all four ids unique')
"
```

- [ ] **Step 5: Commit**

```bash
git add src/packages/web/helpmate_web/static/js/stats-view.js \
        src/packages/web/helpmate_web/static/js/materials.js
git commit -m "refactor(web): extract the statistics renderer from materials.js

No behaviour change. The explorer is about to draw the same charts, and
the ids were unique only while one panel drew them -- #panel-explorer
precedes #panel-materials in the document, so an unprefixed second copy
would have made every existing #dtm-hist query resolve to the wrong
chart rather than merely duplicating an id.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: The explorer shows its table's statistics

**Files:**
- Modify: `src/packages/web/helpmate_web/static/index.html` (a band after the two columns)
- Modify: `src/packages/web/helpmate_web/static/js/explorer.js`
- Modify: `src/packages/web/helpmate_web/static/css/app.css`
- Test: `src/packages/web/tests/ui/test_dashboard.py`

**Interfaces:**
- Consumes: `material` from `/v1/moves` (Task 2); `renderStats(box, stats, { idPrefix, samples })` (Task 5).

- [ ] **Step 1: Write the failing tests**

Append to `src/packages/web/tests/ui/test_dashboard.py`:

```python
def test_the_explorer_shows_the_table_this_position_came_from(page, server):
    page.goto(server)
    page.wait_for_selector("#table-stats .stats-head")
    assert "KQvk" in page.inner_text("#table-stats .stats-head")
    # its own ids, so the Materials panel's charts stay uniquely selectable
    assert page.eval_on_selector_all("#tbl-dtm-hist", "e => e.length") == 1
    assert page.eval_on_selector_all("#dtm-hist", "e => e.length") == 0
    # and no sample list -- the explorer already is a position
    assert page.eval_on_selector_all("#tbl-material-samples", "e => e.length") == 0


def test_the_table_band_is_not_refetched_while_the_material_holds(page, server):
    page.goto(server)
    page.wait_for_selector("#table-stats .stats-head")
    # Match /v1/materials/<name>/stats only. A bare "/stats" would also match
    # the corpus aggregate, which initMaterials() requests on load -- an async
    # call that can land after this patch and turn the test flaky.
    page.evaluate("""() => {
      window.__statsCalls = 0;
      const orig = window.fetch;
      window.fetch = (...a) => {
        if (/\\/v1\\/materials\\/[^/]+\\/stats/.test(String(a[0]))) window.__statsCalls++;
        return orig(...a);
      };
    }""")
    page.click("#move-list li.optimal")
    page.wait_for_function(
        "document.getElementById('position-summary').textContent.includes('dtm')")
    assert page.evaluate("window.__statsCalls") == 0, "refetched the same material"


def test_the_table_band_opens_the_material(page, server):
    page.goto(server)
    page.wait_for_selector("#table-stats .stats-head")
    page.click("#btn-open-material")
    page.wait_for_selector("#panel-materials:not([hidden])")
    assert page.get_attribute(
        "#material-list li[data-material=KQvk]", "aria-selected") == "true"
```

- [ ] **Step 2: Run to verify they fail**

Run: `taskset -c 0-3 make test-web`
Expected: three failures, all timing out waiting for `#table-stats`.

- [ ] **Step 3: Add the band to `index.html`**

Insert immediately after the closing `</div>` of `<div class="readout side">`
and before `</section>` (that is, after line 107, as a third child of
`#panel-explorer`):

```html
    <section id="table-stats" class="table-band" hidden>
      <div class="table-band-head">
        <span class="eyebrow">This table</span>
        <button type="button" id="btn-open-material">Open in Materials</button>
      </div>
      <div id="table-stats-body"></div>
    </section>
```

- [ ] **Step 4: Style it**

Append to the explorer section of `css/app.css`, after the `@media (min-width: 860px)`
block added in Task 4:

```css
/* The band spans both columns: it is context for the whole panel, not an
   answer belonging to the readout. */
.table-band { padding: var(--s3); border-top: 1px solid var(--rule); }
@media (min-width: 860px) { .table-band { grid-column: 1 / -1; } }
.table-band-head { display: flex; align-items: center; gap: var(--s2); }
.table-band-head .eyebrow { margin-right: auto; }
```

- [ ] **Step 5: Implement in `explorer.js`**

Add to the imports at the top:

```js
import { renderStats } from "./stats-view.js";
import { showPanel } from "./panels.js";
```

Add beside the other module state (after `let renderSeq = 0;`):

```js
// The material whose statistics the band is showing, and the payloads we have
// already fetched. Walking a game keeps the same material until a capture or
// a promotion, so this is a cache with a very high hit rate, not an
// optimisation for its own sake.
let bandMaterial = null;
const statsCache = new Map();

async function showTableStats(material) {
  const band = document.getElementById("table-stats");
  const body = document.getElementById("table-stats-body");
  if (!material) { band.hidden = true; bandMaterial = null; return; }
  if (material === bandMaterial) return;
  bandMaterial = material;
  band.hidden = false;
  band.dataset.material = material;

  if (!statsCache.has(material)) {
    try {
      const res = await api.stats(material);
      // A 202 means the table is still downloading. The band is context, not
      // an answer; it stays quiet rather than starting a second poll loop
      // beside the one render() is already running for this position.
      if (res.status !== 200) { band.hidden = true; bandMaterial = null; return; }
      statsCache.set(material, res.body);
    } catch {
      band.hidden = true; bandMaterial = null; return;   // never break the board on context
    }
  }
  if (bandMaterial !== material) return;                 // superseded while awaiting
  renderStats(body, statsCache.get(material), { idPrefix: "tbl-", samples: false });
}
```

In `render()`, after `lastMoves = b.moves;` (line 188), add:

```js
  showTableStats(b.material);
```

In the `kingProblem` early return (after `lastMoves = [];`, line 156) and in
`setArmed`'s enter-edit branch (after `lastMoves = [];`, line 291), add:

```js
    showTableStats(null);
```

so a half-built position does not keep a previous table's numbers on screen.

In `initExplorer()`, wire the button (before the `hashchange` listener):

```js
  document.getElementById("btn-open-material").addEventListener("click", () => {
    const material = document.getElementById("table-stats").dataset.material;
    if (!material) return;
    location.hash = encodeState({ fen: current, panel: "materials" });
    showPanel("materials");
    const li = document.querySelector(`#material-list li[data-material="${material}"]`);
    if (li) li.click();
  });
```

- [ ] **Step 6: Run the tests**

Run: `taskset -c 0-3 make test-web`
Expected: all pass.

- [ ] **Step 7: Check the band against a colour-flipped position**

This is the case that motivated `material` being a server field. Confirm the
band names the table that answered, not the one the FEN spells out:

```bash
taskset -c 0-3 python -c "
from urllib.parse import quote
from playwright.sync_api import sync_playwright
FEN = '8/7K/5k2/8/8/8/8/6q1 w - - 0 1'   # Black holds the queen: Kvkq
with sync_playwright() as pw:
    b = pw.chromium.launch(args=['--no-sandbox']); pg = b.new_page()
    pg.goto('http://127.0.0.1:8642/#fen=' + quote(FEN))
    pg.wait_for_selector('#table-stats .stats-head')
    print('band says:', pg.inner_text('#table-stats .stats-head'))
    print('summary  :', pg.inner_text('#position-summary'))
    b.close()
"
```

Expected: the band says **KQvk** (the mirrored table that answered) while the
summary reports `colors flipped`. **Record the output in the task report.**

- [ ] **Step 8: Commit**

```bash
git add src/packages/web/helpmate_web/static/index.html \
        src/packages/web/helpmate_web/static/css/app.css \
        src/packages/web/helpmate_web/static/js/explorer.js \
        src/packages/web/tests/ui/test_dashboard.py
git commit -m "feat(web): show the current table's statistics under the explorer

A full-width band below both columns, drawn by the same renderer the
Materials panel uses, under its own id prefix. The material comes from
the API rather than from the FEN, because a colour-flipped position is
answered by the mirrored table and deriving it client-side would be
wrong in exactly that case.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: The Materials rail, and "All tables"

Measured: with 295 tables the Materials page renders 12,005px tall, all of it
list, with the statistics panel a postage stamp at the top.

**Files:**
- Modify: `src/packages/web/helpmate_web/static/index.html:110-118`
- Modify: `src/packages/web/helpmate_web/static/js/materials.js`
- Modify: `src/packages/web/helpmate_web/static/js/api.js`
- Modify: `src/packages/web/helpmate_web/static/js/stats-view.js` (add `renderAggregate`)
- Modify: `src/packages/web/helpmate_web/static/css/app.css`
- Test: `src/packages/web/tests/ui/test_dashboard.py`

**Interfaces:**
- Consumes: `GET /v1/stats` (Task 3), `renderStats` / `el` / `tile` / `histogram` / `chart` / `fmtSize` (Task 5), `hasHelpmate` (Task 1).
- Produces: `api.overall()`; `renderAggregate(box, agg)`.

- [ ] **Step 1: Write the failing tests**

Append to `src/packages/web/tests/ui/test_dashboard.py`:

```python
def test_materials_lands_on_the_corpus_summary(page, server):
    page.goto(f"{server}/#panel=materials")
    page.wait_for_function("window.__materialsReady === true")
    page.wait_for_selector("#material-stats .stats-head")
    head = page.inner_text("#material-stats .stats-head")
    assert "All tables" in head
    assert page.get_attribute("#material-list li[data-material='*']", "aria-selected") == "true"
    assert page.eval_on_selector_all("#agg-dtm-hist", "e => e.length") == 1
    # the corpus's uncomfortable facts are stated, not dropped
    assert page.is_visible("#agg-no-helpmate")


def test_the_material_rail_filters(page, server):
    page.goto(f"{server}/#panel=materials")
    page.wait_for_function("window.__materialsReady === true")
    all_names = page.eval_on_selector_all(
        "#material-list li[data-material]:not([hidden])", "els => els.length")
    page.fill("#material-filter", "kqv")
    page.wait_for_function(
        "document.querySelectorAll('#material-list li[data-material]:not([hidden])').length < %d"
        % all_names)
    shown = page.eval_on_selector_all(
        "#material-list li[data-material]:not([hidden])",
        "els => els.map(e => e.dataset.material)")
    assert shown, "the filter hid everything"
    assert all("kqv" in m.lower() for m in shown)
    # "All tables" is never filtered away -- it is the way back
    assert page.is_visible("#material-list li[data-material='*']")


def test_the_material_rail_scrolls_instead_of_the_page(page, server):
    page.set_viewport_size({"width": 1280, "height": 800})
    page.goto(f"{server}/#panel=materials")
    page.wait_for_function("window.__materialsReady === true")
    overflow = page.eval_on_selector("#material-list", "e => getComputedStyle(e).overflowY")
    assert overflow in ("auto", "scroll")
    height = page.evaluate("document.documentElement.scrollHeight")
    assert height < 4000, f"page is {height}px tall; the rail is not containing the list"


def test_the_rail_groups_by_piece_count(page, server):
    page.goto(f"{server}/#panel=materials")
    page.wait_for_function("window.__materialsReady === true")
    heads = page.eval_on_selector_all("#material-list li.group", "els => els.map(e => e.textContent)")
    assert any("PIECES" in h.upper() for h in heads)
```

- [ ] **Step 2: Run to verify they fail**

Run: `taskset -c 0-3 make test-web`
Expected: four failures.

- [ ] **Step 3: Add `api.overall()`**

In `src/packages/web/helpmate_web/static/js/api.js`, add to the `api` object
after `stats`:

```js
  overall: () => getJson("/v1/stats"),
```

- [ ] **Step 4: Add `renderAggregate` to `stats-view.js`**

Append to `src/packages/web/helpmate_web/static/js/stats-view.js`:

```js
// The corpus summary. It shares the tile and histogram vocabulary with a
// single material's view but not its shape: there is no plane_size, no
// sample position, and two facts a per-material view never has to state --
// how many tables contain no helpmate at all, and how many generator
// versions produced the rest. A summary that drops those is not shorter.
export function renderAggregate(box, agg) {
  box.textContent = "";

  const head = el("div", "stats-head");
  head.appendChild(el("h2", null, "All tables"));
  head.appendChild(el("span", "sub",
    `${fmtCount(agg.tables)} tables · ${fmtSize(agg.size_bytes)}`
    + (agg.max_dtm != null ? ` · longest mate h#${agg.max_dtm / 2}` : "")));
  box.appendChild(head);

  const cells = agg.cells || {};
  const tiles = el("div", "tiles");
  tiles.id = "agg-cell-summary";
  tile(tiles, "solvable", fmtCount(cells.solvable || 0));
  tile(tiles, "no mate", fmtCount(cells.unsolvable || 0));
  tile(tiles, "illegal", fmtCount(cells.invalid || 0));
  tile(tiles, "cells total", fmtCount(cells.total || 0));
  box.appendChild(tiles);

  const byPieces = el("div", "tiles");
  byPieces.id = "agg-by-pieces";
  for (const [pieces, n] of Object.entries(agg.tables_by_pieces || {}))
    tile(byPieces, `${pieces} pieces`, fmtCount(n));
  box.appendChild(byPieces);

  // dtmBars/uniquenessBuckets read the aggregate unchanged: the endpoint
  // keeps the sidecar's nested shape and collapses distance under one key.
  const bars = dtmBars(agg);
  if (bars.length) {
    const h = histogram(bars, { barClass: (r) => r.side });
    h.id = "agg-dtm-hist";
    const c = chart("Mate length across every table",
      "How many positions in the whole corpus mate in each distance.", h);
    const legend = el("div", "chart-legend");
    const a = el("span"); a.append(el("i"), document.createTextNode("Black to move"));
    const b = el("span"); b.append(el("i", "wtm"), document.createTextNode("White to move"));
    legend.append(a, b);
    c.appendChild(legend);
    box.appendChild(c);
  }

  const uniq = uniquenessBuckets(agg);
  if (uniq.length) {
    const h = histogram(uniq);
    h.id = "agg-uniqueness-hist";
    box.appendChild(chart("Solutions per position",
      "Summed over every table. One is a sound problem; the counter saturates at 255.", h));
  }

  if ((agg.deepest || []).length) {
    const rows = agg.deepest.map((d) => ({
      label: d.material, positions: d.max_dtm,
      share: d.max_dtm / agg.deepest[0].max_dtm,
    }));
    const h = histogram(rows);
    h.id = "agg-deepest";
    // The bar values are plies; relabel them as distances.
    for (const v of h.querySelectorAll(".v"))
      v.textContent = `h#${Number(v.textContent.replace(/,/g, "")) / 2}`;
    box.appendChild(chart("Deepest tables",
      "The longest helpmate each of these materials contains.", h));
  }

  const none = agg.no_helpmate || [];
  if (none.length) {
    const c = el("div", "chart");
    c.id = "agg-no-helpmate";
    c.appendChild(el("span", "eyebrow", "No helpmate exists"));
    c.appendChild(el("p", "hint",
      `${fmtCount(none.length)} of these materials contain no helpmate at all — `
      + "king and bishop cannot mate, and neither can the rest of this list."));
    const ul = el("ul", "name-list");
    for (const m of none) ul.appendChild(el("li", null, m));
    c.appendChild(ul);
    box.appendChild(c);
  }

  const gens = Object.entries(agg.generators || {}).sort();
  if (gens.length) {
    const c = el("div", "chart");
    c.id = "agg-generators";
    c.appendChild(el("span", "eyebrow", "Generated by"));
    c.appendChild(el("p", "hint",
      gens.length > 1
        ? "This corpus was built by more than one release; a summary that hides that is misleading."
        : "Every table here came from one release."));
    const tiles2 = el("div", "tiles");
    for (const [v, n] of gens) tile(tiles2, v, fmtCount(n));
    c.appendChild(tiles2);
    box.appendChild(c);
  }

  if (agg.tables_without_stats)
    box.appendChild(el("p", "hint",
      `${fmtCount(agg.tables_without_stats)} table(s) have no local statistics file and are counted but not summed.`));
}
```

`renderAggregate` uses `dtmBars`, `uniquenessBuckets` and `fmtCount`, all of
which Task 5 already imports into this file. No import change is needed —
confirm the existing line still reads:

```js
import { dtmBars, uniquenessBuckets, cellSummary, fmtCount, mateLengthLabel } from "./lib/stats.js";
```

- [ ] **Step 5: Rebuild the rail markup**

Replace `#panel-materials` in `index.html` (lines 110-118) with:

```html
  <section id="panel-materials" hidden>
    <div class="rail list-col">
      <h2 class="eyebrow">Tables</h2>
      <label class="sr-label" for="material-filter">Filter tables</label>
      <input id="material-filter" type="search" autocomplete="off" spellcheck="false"
             placeholder="filter, e.g. kq">
      <ul id="material-list"></ul>
    </div>
    <div id="material-stats" class="readout detail-col"></div>
  </section>
```

The help paragraph is gone: the filter box and the "All tables" entry explain
the list better than a sentence above it did.

- [ ] **Step 6: Rewrite `initMaterials`**

Replace `initMaterials` in `materials.js` with:

```js
const ALL = "*";   // the pinned "All tables" entry's data-material

function applyFilter(list, term) {
  const q = term.trim().toLowerCase();
  for (const li of list.children) {
    // "All tables" is never filtered away -- it is the way back to the
    // summary, and hiding it would strand a user who typed a term matching
    // nothing. Group headings go while a filter is active: with the list
    // narrowed to a handful, "4 PIECES" over one row is furniture.
    if (li.dataset.material === ALL) { li.hidden = false; continue; }
    if (li.classList.contains("group")) { li.hidden = Boolean(q); continue; }
    li.hidden = Boolean(q) && !li.dataset.material.toLowerCase().includes(q);
  }
}

async function showOverall() {
  const seq = ++statsSeq;
  const box = document.getElementById("material-stats");
  box.textContent = "";
  box.appendChild(el("p", "empty", "Summing every table…"));
  try {
    const res = await api.overall();
    if (seq !== statsSeq) return;
    renderAggregate(box, res.body);
  } catch (err) {
    if (seq !== statsSeq) return;
    if (!(err instanceof ApiError)) throw err;
    box.textContent = "";
    box.appendChild(el("p", "empty", err.hint ? `${err.message} — ${err.hint}` : err.message));
  }
}

export async function initMaterials() {
  const list = document.getElementById("material-list");
  const filter = document.getElementById("material-filter");
  list.textContent = "";
  list.appendChild(el("li", "empty", "Loading…"));

  let res;
  try { res = await api.materials(); }
  catch (err) {
    list.textContent = "";
    if (err instanceof ApiError) {
      list.appendChild(el("li", "empty", err.hint ? `${err.message} — ${err.hint}` : err.message));
      window.__materialsReady = true;
      return;
    }
    throw err;
  }

  const select = (li, run) => {
    for (const other of list.children) other.removeAttribute("aria-selected");
    li.setAttribute("aria-selected", "true");
    run();
  };

  list.textContent = "";
  const all = el("li", "all");
  all.dataset.material = ALL;
  all.append(el("span", "name", "All tables"),
             el("span", "meta", `  ${res.body.materials.length} tables`));
  all.addEventListener("click", () => select(all, showOverall));
  list.appendChild(all);

  if (!res.body.materials.length)
    list.appendChild(el("li", "empty", "No tables yet. Generate one with `helpmate gen KQvk`."));

  // Grouped by piece count, in the order the catalog already sorts them.
  let group = null;
  for (const m of [...res.body.materials].sort((a, b) => a.pieces - b.pieces
                                                       || a.material.localeCompare(b.material))) {
    if (m.pieces !== group) {
      group = m.pieces;
      const h = el("li", "group", `${group} pieces`);
      list.appendChild(h);
    }
    const li = el("li");
    li.append(el("span", "name", m.material),
              el("span", "meta", `  ${fmtSize(m.size_bytes)} · ${m.location}`));
    li.dataset.material = m.material;
    li.addEventListener("click", () => select(li, () => showStats(m.material)));
    list.appendChild(li);
  }

  filter.addEventListener("input", () => applyFilter(list, filter.value));

  select(all, showOverall);
  window.__materialsReady = true;
}
```

Extend the imports at the top of `materials.js`:

```js
import { fmtSize, el, renderStats, renderAggregate } from "./stats-view.js";
```

- [ ] **Step 7: Style the rail**

Replace the `/* ---------- materials ---------- */` layout rules
(`#panel-materials`, `.list-col`, `.detail-col`) with:

```css
#panel-materials { display: flex; flex-direction: column; }
.list-col { display: flex; flex-direction: column; gap: var(--s2); }
#material-filter { width: 100%; font-size: var(--f2); }
/* The rail scrolls, so the page height stops being a function of how many
   tables the server can reach. 295 of them rendered 12,005px tall. */
#material-list { overflow-y: auto; max-height: 60vh; margin: 0; }
#material-list li.group {
  border: 0; background: none; cursor: default; padding: var(--s3) 0 .2rem;
  font-size: var(--f0); font-weight: 600; letter-spacing: .1em;
  text-transform: uppercase; color: var(--ink-soft);
}
#material-list li.all { font-weight: 650; }
.name-list { list-style: none; padding: 0; margin: var(--s2) 0 0;
             display: flex; flex-wrap: wrap; gap: .3rem;
             font-family: var(--mono); font-size: var(--f1); }
.name-list li { border: 1px solid var(--rule); border-radius: 3px; padding: .1rem .4rem; }
/* Visible to a screen reader, out of the way of the eye: the filter's
   placeholder is a hint, not a label. */
.sr-label {
  position: absolute; width: 1px; height: 1px; overflow: hidden;
  clip-path: inset(50%); white-space: nowrap;
}

@media (min-width: 860px) {
  #panel-materials {
    display: grid; grid-template-columns: minmax(240px, 320px) minmax(320px, 1fr);
    align-items: start;
  }
  .list-col { position: sticky; top: var(--s3); }
  #material-list { max-height: calc(100vh - 12rem); }
}
```

- [ ] **Step 8: Run the tests**

Run: `taskset -c 0-3 make test-web`
Expected: all pass. `test_materials_panel_lists_tables_and_opens_a_sample`
still clicks `#material-list li[data-material=KQvk]` and waits for
`#material-samples li` — both survive, because the per-material path still
renders with the default (empty) id prefix and samples enabled.

- [ ] **Step 9: Check it against 295 tables, not 2**

The fixture generates a handful of tables; the defect this task fixes only
appears at corpus scale. Point a browser at the live server:

```bash
taskset -c 0-3 python -c "
from playwright.sync_api import sync_playwright
with sync_playwright() as pw:
    b = pw.chromium.launch(args=['--no-sandbox'])
    pg = b.new_page(viewport={'width':1280,'height':900})
    pg.goto('http://127.0.0.1:8642/#panel=materials')
    pg.wait_for_selector('#agg-dtm-hist')
    print('page height:', pg.evaluate('document.documentElement.scrollHeight'))
    print('head:', pg.inner_text('#material-stats .stats-head'))
    print('no-helpmate count:', pg.inner_text('#agg-no-helpmate .hint'))
    pg.screenshot(path='/tmp/claude-1000/.../scratchpad/t7-materials.png', full_page=True)
    b.close()
"
```

Expected: page height well under 4000px (it was 12,005), the head reads
`All tables — 295 tables · 41.4 GB · longest mate h#17`, and the no-helpmate
note names 67. **Record all three in the task report, with the screenshot.**

- [ ] **Step 10: Commit**

```bash
git add src/packages/web/helpmate_web/static/index.html \
        src/packages/web/helpmate_web/static/css/app.css \
        src/packages/web/helpmate_web/static/js/materials.js \
        src/packages/web/helpmate_web/static/js/stats-view.js \
        src/packages/web/helpmate_web/static/js/api.js \
        src/packages/web/tests/ui/test_dashboard.py
git commit -m "feat(web): a scrolling, filterable material rail and a corpus summary

295 tables rendered the Materials page 12,005px tall with the statistics
panel a postage stamp at the top. The list now scrolls inside the rail,
filters on substring and groups by piece count.

'All tables' is the landing state and answers the question no per-table
view can: the whole corpus at once, including the two facts a summary is
tempted to drop -- the 67 materials that contain no helpmate at all, and
the seven generator versions that built the rest.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: Search — an honest timeout, a Stop button, a visible budget

Today the server's 30s timeout comes back as `{fens: [], truncated: true,
note: "timeout"}` and `mine.js` renders it as `0 position(s) (truncated —
raise max results for more)`: advice that cannot help, about a result that was
never computed.

**Files:**
- Modify: `src/packages/web/helpmate_web/static/js/api.js`
- Modify: `src/packages/web/helpmate_web/static/js/mine.js`
- Modify: `src/packages/web/helpmate_web/static/index.html:120-148`
- Modify: `src/packages/web/helpmate_web/static/css/app.css`
- Test: `src/packages/web/tests/js/api.test.js`, `src/packages/web/tests/ui/test_dashboard.py`

**Interfaces:**
- Consumes: `mine_timeout` from `/v1/health` (Task 2).
- Produces: `getJson(path, params, { signal })`, `api.mine(q, { signal })`.

- [ ] **Step 1: Write the failing node test**

Append to `src/packages/web/tests/js/api.test.js`:

```js
test("an aborted request rethrows AbortError, not a network ApiError", async () => {
  // The catch around fetch() turns every throw into ApiError(0, "network").
  // An abort is not a network failure -- the caller asked for it -- and the
  // search screen has to tell them apart to avoid reporting "cannot reach
  // the server" every time the user presses Stop.
  const ctl = new AbortController();
  global.fetch = () => {
    const e = new Error("aborted");
    e.name = "AbortError";
    return Promise.reject(e);
  };
  await assert.rejects(
    () => getJson("/v1/mine", { material: "KQvk" }, { signal: ctl.signal }),
    (err) => err.name === "AbortError",
  );
});
```

Match the file's existing `global.fetch` / `window.location.origin` stubbing
style; read the top of `api.test.js` before writing and reuse it.

- [ ] **Step 2: Run to verify it fails**

Run: `taskset -c 0-3 make jstest`
Expected: FAIL — the rejection is an `ApiError`, not an `AbortError`.

- [ ] **Step 3: Plumb the signal through `api.js`**

Change `getJson`'s signature and its fetch/catch (lines 19, 31-39):

```js
export async function getJson(path, params = {}, { signal } = {}) {
```

```js
  let res;
  try {
    res = await fetch(url, { signal });
  } catch (err) {
    // An abort is not a network failure -- the caller asked for it. Let it
    // through unchanged so callers can distinguish "you pressed Stop" from
    // "the server is unreachable".
    if (err && err.name === "AbortError") throw err;
    // status 0 marks "no HTTP response was received at all" (server down,
    // DNS failure, CORS block) so callers can tell it apart from a real
    // HTTP error status and don't have to also handle a raw TypeError.
    throw new ApiError(0, "network", "cannot reach the server", null);
  }
```

and the `mine` entry:

```js
  mine: (q, opts) => getJson("/v1/mine", q, opts),
```

- [ ] **Step 4: Run the node test**

Run: `taskset -c 0-3 make jstest`
Expected: PASS.

- [ ] **Step 5: Write the failing UI tests**

Append to `src/packages/web/tests/ui/test_dashboard.py`:

```python
def test_a_timed_out_search_says_so_instead_of_reporting_no_results(page, server):
    # The server answers a timeout with {fens: [], truncated: true,
    # note: "timeout"}. Rendering that as "0 position(s) (truncated -- raise
    # max results for more)" is advice that cannot help, about a result that
    # was never computed.
    page.goto(f"{server}/#panel=mine")
    page.route("**/v1/mine**", lambda route: route.fulfill(
        status=200, content_type="application/json",
        body='{"fens": [], "truncated": true, "note": "timeout", "skipped_saturated": 0}'))
    page.fill("#mine-form input[name=material]", "KQvk")
    page.fill("#mine-form input[name=dtm]", "2")
    page.click("#mine-form button[type=submit]")
    page.wait_for_function(
        "document.getElementById('mine-status').textContent.toLowerCase().includes('timed out')")
    status = page.inner_text("#mine-status")
    assert "raise max results" not in status
    assert "0 position(s)" not in status


def test_the_search_button_becomes_stop_while_in_flight(page, server):
    page.goto(f"{server}/#panel=mine")
    page.route("**/v1/mine**", lambda route: None)   # never respond
    page.fill("#mine-form input[name=material]", "KQvk")
    page.fill("#mine-form input[name=dtm]", "2")
    page.click("#mine-form button[type=submit]")
    page.wait_for_selector("#btn-stop:not([hidden])")
    page.wait_for_function(
        "document.getElementById('mine-status').textContent.includes('of ')")
    page.click("#btn-stop")
    page.wait_for_function(
        "document.getElementById('mine-status').textContent.toLowerCase().includes('stopped')")
    assert page.is_hidden("#btn-stop")
    assert page.is_visible("#mine-form button[type=submit]")


def test_the_countdown_uses_the_servers_budget(page, server):
    page.goto(f"{server}/#panel=mine")
    page.route("**/v1/mine**", lambda route: None)
    page.fill("#mine-form input[name=material]", "KQvk")
    page.fill("#mine-form input[name=dtm]", "2")
    page.click("#mine-form button[type=submit]")
    page.wait_for_function(
        "document.getElementById('mine-status').textContent.includes('of 30s')")
```

- [ ] **Step 6: Rebuild the search markup**

Replace `#panel-mine` in `index.html` (lines 120-148) with:

```html
  <section id="panel-mine" hidden>
    <form id="mine-form" class="rail">
      <h2 class="eyebrow">Search a material</h2>
      <label>Material <input name="material" required placeholder="KQvk" autocomplete="off"></label>
      <label>dtm (plies) <input name="dtm" type="number" min="0" required></label>
      <label>count <input name="count" type="number" min="1" placeholder="any"></label>
      <label>starts <input name="starts" type="number" min="1" placeholder="any"></label>
      <label>ends <input name="ends" type="number" min="1" placeholder="any"></label>
      <label>themes
        <select id="mine-themes" name="theme" multiple size="6"></select>
        <small class="hint">optional — a position must show every theme you pick, though not necessarily in the same solution</small>
      </label>
      <label>max results <input name="max" type="number" min="1" value="50"></label>
      <div class="row">
        <button type="submit">Search</button>
        <button type="button" id="btn-stop" hidden>Stop</button>
      </div>
    </form>

    <div class="readout">
      <p class="help">
        Find positions by mate length and by the shape of their solution set.
        <b>starts</b> is how many different first moves the optimal solutions
        use, <b>ends</b> how many different mating moves they finish on — one
        start and one end is a clean single-solution problem; four starts
        converging on one end is a theme.
      </p>
      <p id="mine-status" class="verdict"></p>
      <ul id="mine-results"></ul>
      <div class="row">
        <button type="button" id="btn-export-fens">Download FENs</button>
        <button type="button" id="btn-export-csv">Download CSV</button>
      </div>
    </div>
  </section>
```

- [ ] **Step 7: Implement in `mine.js`**

Add module state beside `mineSeq`:

```js
// The server's own budget, so the countdown is not a number hardcoded here.
// 30 matches main.py's --mine-timeout default and is only ever the fallback
// for a health call that failed.
let budgetSeconds = 30;
let inFlight = null;     // the AbortController of the running search
let ticker = null;       // the elapsed-time interval
```

Add the elapsed helpers above `runQuery`:

```js
function startTicker(status) {
  const began = Date.now();
  const tick = () => {
    const secs = Math.floor((Date.now() - began) / 1000);
    status.textContent = `searching… ${secs}s of ${budgetSeconds}s`;
  };
  tick();
  ticker = setInterval(tick, 1000);
}

function stopTicker() {
  if (ticker !== null) { clearInterval(ticker); ticker = null; }
}

// Which controls are live. One function so the two buttons can never
// disagree about whether a search is running.
function setBusy(busy) {
  document.querySelector("#mine-form button[type=submit]").hidden = busy;
  document.getElementById("btn-stop").hidden = !busy;
}
```

In `runQuery`, take the controller and honour the timeout note. Replace the
signature and the head of the function:

```js
async function runQuery(q, status, results, seq, retries = 0) {
  let res;
  try { res = await api.mine(q, { signal: inFlight ? inFlight.signal : undefined }); }
  catch (err) {
    if (err && err.name === "AbortError") return;   // the user pressed Stop
    if (seq !== mineSeq) return;   // superseded by a newer search
    if (err instanceof ApiError) { status.textContent = err.hint ? `${err.message} — ${err.hint}` : err.message; return; }
    throw err;
  }
```

and replace the result-reporting block (the `const b = res.body;` paragraph)
with:

```js
  const b = res.body;
  // A timeout is not a result. The server answers it with an empty list and
  // truncated: true, which the generic branch below would render as
  // "0 position(s) (truncated -- raise max results for more)" -- advice that
  // cannot help, about a scan that never finished.
  if (b.note === "timeout") {
    rows = [];
    status.textContent =
      `Timed out after ${budgetSeconds}s. No results yet — narrow the material, `
      + "or drop the count/starts/ends filters.";
    return;
  }
  rows = b.fens.map((fen) => ({ fen, dtm: Number(q.dtm), count: q.count === "" ? "" : Number(q.count) }));
  status.textContent =
    `${b.fens.length} position(s)` +
    (b.truncated ? " (truncated — raise max results for more)" : "") +
    (b.skipped_saturated ? ` · ${b.skipped_saturated} skipped (count saturated)` : "");
```

In `initMine`, read the budget and wire Stop. Add after the themes fetch:

```js
  api.health().then(({ body }) => {
    if (typeof body.mine_timeout === "number" && body.mine_timeout > 0)
      budgetSeconds = body.mine_timeout;
  }).catch(() => { /* keep the default; the countdown is a nicety */ });

  document.getElementById("btn-stop").addEventListener("click", () => {
    if (inFlight) inFlight.abort();
    inFlight = null;
    stopTicker();
    setBusy(false);
    mineSeq++;   // retire any scheduled 202 retry
    // Honest about what aborting does and does not do: the scan runs in the
    // server's thread pool and abandoning the response does not free it.
    status.textContent = "Stopped. The server finishes or drops this scan within "
      + `${budgetSeconds}s.`;
  });
```

and wrap the submit handler's call so the busy state and the ticker always
unwind — replace the tail of the submit listener:

```js
    status.textContent = "searching…";
    const seq = ++mineSeq;
    inFlight = new AbortController();
    setBusy(true);
    startTicker(status);
    try {
      await runQuery(q, status, results, seq);
    } finally {
      if (seq === mineSeq) { stopTicker(); setBusy(false); inFlight = null; }
    }
```

The `seq === mineSeq` guard matters: `runQuery`'s 202 branch schedules a retry
and returns, and Stop bumps `mineSeq` — without the guard, a superseded
search's `finally` would clear the *current* search's busy state.

- [ ] **Step 8: Style the search rail**

Replace the **whole** existing `#mine-form` rule, not just its layout lines.
It currently sets `background: var(--panel)` and an `#mine-form` id selector
outranks the `.rail` class, so leaving that declaration behind would paint the
rail white and quietly undo the split on this one screen.

Replace the `/* ---------- search ---------- */` block's layout rules with:

```css
#panel-mine { display: flex; flex-direction: column; }
#mine-form {
  display: flex; flex-direction: column; align-items: stretch; gap: var(--s2);
  margin: 0; border: 0;
}
#mine-form label { display: flex; flex-direction: column; gap: .2rem;
                   font-size: var(--f1); color: var(--ink-soft); }
#mine-form input { width: 100%; font-family: var(--mono); font-size: var(--f2); }
#mine-form select[multiple] { width: 100%; }
#mine-form .hint { display: block; opacity: 0.7; font-size: 0.85em; }
#panel-mine .row { margin-top: .75rem; }

@media (min-width: 860px) {
  #panel-mine {
    display: grid; grid-template-columns: minmax(220px, 300px) minmax(320px, 1fr);
    align-items: start;
  }
  #mine-form { position: sticky; top: var(--s3); }
}
```

Delete the now-dead `#panel-mine { max-width: 900px; }` and
`#mine-form input[name="material"] { width: 9rem; }` rules.

- [ ] **Step 9: Run the tests**

Run: `taskset -c 0-3 make jstest && taskset -c 0-3 make test-web`
Expected: all pass.

- [ ] **Step 10: Drive a real timeout end to end**

The UI test mocks the response. Prove the real path too, against a search
big enough to blow the budget — read-only, no writes to `~/tb`:

```bash
GIT_CONFIG_GLOBAL=/dev/null taskset -c 0-3 helpmate-server \
  --tables ~/tb --port 8643 --mine-timeout 3 &
sleep 3
curl -s "http://127.0.0.1:8643/v1/mine?material=KBvkqrb&dtm=8&count=1&max=50" | head -c 200
echo
pkill -f "helpmate[-]server.*8643"
```

Expected: `{"fens":[],"truncated":true,"note":"timeout",...}`. Then open
`http://127.0.0.1:8643/#panel=mine` in the same configuration and confirm by
eye that the counter runs `of 3s` and the message names the timeout.
**Record the JSON and what the screen said.**

- [ ] **Step 11: Commit**

```bash
git add src/packages/web/helpmate_web/static/js/api.js \
        src/packages/web/helpmate_web/static/js/mine.js \
        src/packages/web/helpmate_web/static/index.html \
        src/packages/web/helpmate_web/static/css/app.css \
        src/packages/web/tests/js/api.test.js \
        src/packages/web/tests/ui/test_dashboard.py
git commit -m "feat(web): a Stop button, a visible budget, and an honest timeout

A timed-out search came back as {fens: [], truncated: true} and rendered
as '0 position(s) (truncated -- raise max results for more)': advice that
cannot help, about a scan that never finished. It now names the timeout.

Stop aborts the fetch and says what that does and does not do -- the scan
runs in the server's thread pool and abandoning the response does not
free the worker. Real cancellation belongs to the concurrency phase.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 9: Drag and drop into the position editor

**Files:**
- Create: `src/packages/web/helpmate_web/static/js/lib/board-edit.js`
- Create: `src/packages/web/tests/js/board-edit.test.js`
- Modify: `src/packages/web/helpmate_web/static/js/explorer.js`
- Modify: `src/packages/web/helpmate_web/static/index.html`
- Modify: `src/packages/web/helpmate_web/static/css/app.css`
- Test: `src/packages/web/tests/ui/test_dashboard.py`

**Interfaces:**
- Produces: `squareFromTarget(el)`, `DRAG_THRESHOLD_PX`, `exceedsDragThreshold(a, b)` from `js/lib/board-edit.js`.

Why these and not a pixel-to-square function: cm-chessboard tags every square
rect with `data-square` (`view/ChessboardView.js:193`), so the hit test is
`document.elementFromPoint` plus a walk up the tree — more robust than
geometry, because it handles the coordinate frame, the orientation and any
future border type for free. What is worth pinning in a unit test is the walk
and the click-versus-drag threshold.

**Read this before writing any code — the two board gestures cannot share a
mode.** `enableSquareSelect(POINTER_EVENTS.pointerdown, …)` (click to place)
and `enableMoveInput` (drag to rearrange) both bind `pointerdown`. Enabling
them together means pressing on g1 to drag its queen away *first places the
armed piece on g1*, and cm-chessboard's move input additionally treats
click-then-click as a move, so a plain click becomes ambiguous too. Neither
failure is visible in a screenshot; both are visible immediately in the hand
check at Step 10.

So arming is a **four-way** toggle, and each value owns exactly one gesture:

| `armed` | mode | square-select | move-input |
|---|---|---|---|
| `null` | play | off | validate against `lastMoves` |
| `"wq"` … | place | on (click a square) | **off** |
| `""` | erase | on (click a square) | **off** |
| `ARRANGE` | arrange | **off** | accept everything; off-board removes |

`ARRANGE` is a new palette control beside Erase. Clicking the armed control a
second time exits and evaluates, exactly as every other palette entry already
does — which is what keeps
`test_the_palette_places_a_piece_and_evaluates_on_exit` green and means no
existing state handling has to change. A palette drag arms the dragged piece
(place mode), so you can drop several without going back to the palette.

- [ ] **Step 1: Write the failing node test**

Create `src/packages/web/tests/js/board-edit.test.js`:

```js
import test from "node:test";
import assert from "node:assert/strict";
import {
  squareFromTarget, exceedsDragThreshold, DRAG_THRESHOLD_PX,
} from "../../helpmate_web/static/js/lib/board-edit.js";

// Plain objects, not a DOM: the walk is deliberately written against
// `dataset` and `parentElement` so it needs neither jsdom nor a browser.
const node = (square, parent = null) => ({
  dataset: square ? { square } : {},
  parentElement: parent,
});

test("a square rect answers with its own square", () => {
  assert.equal(squareFromTarget(node("e4")), "e4");
});

test("a piece dropped on a square finds it by walking up", () => {
  const board = node(null, null);
  const rect = node("a1", board);
  const piece = node(null, rect);
  assert.equal(squareFromTarget(piece), "a1");
});

test("a target outside the board answers null, not a guess", () => {
  assert.equal(squareFromTarget(node(null, node(null, null))), null);
  assert.equal(squareFromTarget(null), null);
});

test("the nearest square wins over an ancestor's", () => {
  assert.equal(squareFromTarget(node("h8", node("a1"))), "h8");
});

test("a small movement is a click, not a drag", () => {
  assert.equal(exceedsDragThreshold({ x: 0, y: 0 }, { x: 1, y: 1 }), false);
  assert.equal(exceedsDragThreshold({ x: 0, y: 0 }, { x: DRAG_THRESHOLD_PX + 1, y: 0 }), true);
  assert.equal(exceedsDragThreshold({ x: 10, y: 10 }, { x: 10, y: 10 - DRAG_THRESHOLD_PX - 1 }), true);
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `taskset -c 0-3 make jstest`
Expected: FAIL — `Cannot find module .../lib/board-edit.js`.

- [ ] **Step 3: Implement `board-edit.js`**

Create `src/packages/web/helpmate_web/static/js/lib/board-edit.js`:

```js
// Drag helpers for the position editor. No DOM APIs and no board -- the walk
// is written against `dataset` and `parentElement` so it is testable with
// plain objects, and so `elementFromPoint` stays the caller's business.
//
// cm-chessboard tags every square rect with data-square
// (vendor/cm-chessboard/view/ChessboardView.js:193), which makes the hit test
// a tree walk rather than geometry -- and so it survives the coordinate
// frame, the board's orientation and any future border type without knowing
// about any of them.

// Below this, a pointer gesture is a click and the palette button must still
// behave like a button. Four CSS pixels is the usual floor for a deliberate
// drag and matches what a shaky hand on a trackpad produces.
export const DRAG_THRESHOLD_PX = 4;

export function squareFromTarget(el) {
  for (let n = el; n; n = n.parentElement) {
    const square = n.dataset && n.dataset.square;
    if (square) return square;
  }
  return null;
}

export function exceedsDragThreshold(from, to) {
  if (!from || !to) return false;
  const dx = to.x - from.x;
  const dy = to.y - from.y;
  return Math.hypot(dx, dy) > DRAG_THRESHOLD_PX;
}
```

- [ ] **Step 4: Run the node test**

Run: `taskset -c 0-3 make jstest`
Expected: PASS.

- [ ] **Step 5: Write the failing UI tests**

Append to `src/packages/web/tests/ui/test_dashboard.py`:

```python
def test_dragging_a_piece_from_the_palette_places_it(page, server):
    page.goto(server)
    page.wait_for_selector("#move-list li")
    src = page.locator("#palette-pieces button[data-piece=wr]")
    dst = page.locator("#board rect[data-square=d4]")
    src.drag_to(dst)
    page.wait_for_function(
        "document.getElementById('fen-input').value.split(' ')[0].includes('R')")
    placement = page.input_value("#fen-input").split()[0]
    assert placement.split("/")[4].startswith("3R"), placement
    # a drag enters edit mode, so the previous position's value is retired
    assert "dtm" not in page.inner_text("#position-summary")
    assert page.is_visible("#btn-done-editing")


def test_dragging_a_piece_off_the_board_removes_it(page, server):
    # The landing position has a white queen on g1. Enter edit mode, drag it
    # past the left edge of the window, and it should be gone.
    page.goto(server)
    page.wait_for_selector("#move-list li")
    before = page.input_value("#fen-input")
    assert "Q" in before.split()[0]

    page.click("#btn-arrange")            # arrange mode: drag, don't place
    page.wait_for_selector("#btn-done-editing:not([hidden])")
    assert page.get_attribute("#btn-arrange", "aria-pressed") == "true"

    box = page.locator("#board rect[data-square=g1]").bounding_box()
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    page.mouse.down()
    page.mouse.move(box["x"] - 300, box["y"] + 300, steps=12)   # off the board
    page.mouse.up()

    page.wait_for_function(
        "before => document.getElementById('fen-input').value !== before", arg=before)
    assert "Q" not in page.input_value("#fen-input").split()[0]


def test_done_evaluates_and_leaves_edit_mode(page, server):
    page.goto(server)
    page.wait_for_selector("#move-list li")
    src = page.locator("#palette-pieces button[data-piece=wr]")
    dst = page.locator("#board rect[data-square=d4]")
    src.drag_to(dst)
    page.wait_for_selector("#btn-done-editing:not([hidden])")
    page.click("#btn-done-editing")
    page.wait_for_function(
        "document.getElementById('position-summary').textContent.length > 0")
    assert page.is_hidden("#btn-done-editing")
```

- [ ] **Step 6: Run to verify they fail**

Run: `taskset -c 0-3 make test-web`
Expected: three failures.

- [ ] **Step 7: Add the Done button and the drag ghost**

In `index.html`, replace the `.palette-actions` div and the hint (lines 48-56):

```html
        <div class="palette-actions">
          <button type="button" id="btn-erase" data-piece="">Erase</button>
          <button type="button" id="btn-arrange" data-piece="arrange">Arrange</button>
          <button type="button" id="btn-clear-board">Clear board</button>
          <button type="button" id="btn-done-editing" hidden>Done — evaluate</button>
        </div>
        <p id="edit-hint" class="hint">
          Drag a piece from here onto the board, or pick one and click squares.
          <b>Arrange</b> drags the pieces already on the board — off the edge
          removes them.
        </p>
```

In `css/app.css`, after the `.palette button[aria-pressed="true"]` rule:

```css
/* The piece under the pointer during a palette drag. Fixed to the viewport
   and inert, so elementFromPoint sees the square underneath rather than the
   ghost itself. */
.drag-ghost {
  position: fixed; z-index: 10; width: 2.6rem; height: 2.6rem;
  pointer-events: none; opacity: .85;
}
#btn-done-editing { font-weight: 600; }
```

- [ ] **Step 8: Implement the drag in `explorer.js`**

Add to the imports:

```js
import { MOVE_CANCELED_REASON } from "../vendor/cm-chessboard/view/VisualMoveInput.js";
import { squareFromTarget, exceedsDragThreshold } from "./lib/board-edit.js";
```

Add after `buildPalette()`'s definition:

```js
// Dragging a piece out of the palette and onto a square. cm-chessboard has no
// notion of an external drag source, so this is ours: capture the pointer,
// carry a ghost, and ask the document what is under the pointer on release.
// The board's own data-square attributes do the hit testing, so orientation
// and the coordinate frame need no arithmetic here.
function enablePaletteDrag(btn, piece) {
  btn.addEventListener("pointerdown", (down) => {
    if (down.button !== 0) return;
    const from = { x: down.clientX, y: down.clientY };
    let ghost = null;

    const move = (e) => {
      if (!ghost) {
        if (!exceedsDragThreshold(from, { x: e.clientX, y: e.clientY })) return;
        // Past the threshold this is a drag, so arm the piece (which puts the
        // board in edit mode) and stop the click handler from also firing.
        if (armed !== piece) setArmed(piece);
        ghost = btn.cloneNode(true);
        ghost.className = "drag-ghost";
        ghost.removeAttribute("id");
        document.body.appendChild(ghost);
      }
      ghost.style.left = `${e.clientX - 20}px`;
      ghost.style.top = `${e.clientY - 20}px`;
    };

    const up = (e) => {
      btn.removeEventListener("pointermove", move);
      btn.removeEventListener("pointerup", up);
      btn.removeEventListener("pointercancel", up);
      if (!ghost) return;                       // it was a click; let click handle it
      ghost.remove();
      ghost = null;
      down.preventDefault();
      const square = squareFromTarget(document.elementFromPoint(e.clientX, e.clientY));
      if (!square) return;                      // dropped off the board: no-op
      board.setPiece(square, piece).then(() => {
        const fen = withPlacement(current, board.getPosition());
        current = fen;
        syncControls(fen);
      });
    };

    btn.setPointerCapture(down.pointerId);
    btn.addEventListener("pointermove", move);
    btn.addEventListener("pointerup", up);
    btn.addEventListener("pointercancel", up);
  });
}
```

In `buildPalette`, call it for each piece — after the existing
`btn.addEventListener("click", ...)` line:

```js
    enablePaletteDrag(btn, piece);
```

Guard the click handler so a completed drag does not also toggle the arming.
Replace that click listener with:

```js
    btn.addEventListener("click", () => {
      if (btn.dataset.dragged === "1") { delete btn.dataset.dragged; return; }
      setArmed(armed === piece ? null : piece);
    });
```

and in `up`, immediately after `down.preventDefault();`, add:

```js
      btn.dataset.dragged = "1";
```

Free rearrangement and off-board removal while editing — add above
`enableDragToPlay`:

```js
// While editing, a drag means "move this piece there" (any square, legal or
// not) and a drag off the board means "remove it". cm-chessboard raises both;
// we simply stopped ignoring them.
function enableDragToEdit() {
  board.enableMoveInput((event) => {
    if (event.type === INPUT_EVENT_TYPE.validateMoveInput) return true;
    if (event.type === INPUT_EVENT_TYPE.moveInputCanceled
        && event.reason === MOVE_CANCELED_REASON.movedOutOfBoard) {
      board.setPiece(event.squareFrom, null).then(syncFromBoard);
      return;
    }
    if (event.type === INPUT_EVENT_TYPE.moveInputFinished) syncFromBoard();
    return true;
  });
}

function syncFromBoard() {
  const fen = withPlacement(current, board.getPosition());
  current = fen;
  syncControls(fen);
}
```

Declare the arrange sentinel beside `PALETTE` at the top of the file:

```js
// The fourth arming state. A piece name places, "" erases, null plays -- and
// this drags what is already on the board. It is a distinct value rather than
// a flag because click-to-place and drag-to-rearrange both bind pointerdown,
// so exactly one of them may be live at a time.
const ARRANGE = "arrange";
```

Now rebind the board's input on **every** arming change, not only on entering
edit mode — the mode is a function of `armed`, and `armed` changes without
`wasEditing` changing (piece → Erase → Arrange). Replace the whole body of
`setArmed` below the `aria-pressed` loop with:

```js
  const done = document.getElementById("btn-done-editing");

  // Exactly one input binding is live at a time. Rebinding unconditionally is
  // cheaper to reason about than working out which transitions need which
  // call, and cm-chessboard's disable* calls are safe when nothing is bound.
  board.disableSquareSelect(POINTER_EVENTS.pointerdown);
  board.disableMoveInput();

  if (armed === null) {
    enableDragToPlay();
    done.hidden = true;
    if (wasEditing && commit) commitBoard();
    return;
  }

  if (armed === ARRANGE) enableDragToEdit();
  else board.enableSquareSelect(POINTER_EVENTS.pointerdown, onSquareClick);
  done.hidden = false;

  if (!wasEditing) {
    // The previous position's value belongs to a position that no longer
    // exists. Leaving it on screen while pieces move around would present a
    // stale dtm as the current one; say what is happening instead.
    const summary = document.getElementById("position-summary");
    summary.textContent = "editing — press Done to evaluate";
    summary.classList.add("muted");
    document.getElementById("position-themes").textContent = "";
    document.getElementById("move-list").textContent = "";
    const linesEl = document.getElementById("lines");
    linesEl.textContent = ""; linesEl.dataset.lines = "[]";
    lastMoves = [];
    showTableStats(null);
  }
```

Note that the `aria-pressed` loop above already covers the new button, because
it selects `#palette button` and `#btn-arrange` carries `data-piece="arrange"`.

Wire the two new buttons in `buildPalette`, beside the existing `#btn-erase`
line:

```js
  const arrange = document.getElementById("btn-arrange");
  arrange.setAttribute("aria-pressed", "false");
  arrange.addEventListener("click", () => setArmed(armed === ARRANGE ? null : ARRANGE));
```

and in `initExplorer()`:

```js
  document.getElementById("btn-done-editing").addEventListener("click", () => setArmed(null));
```

- [ ] **Step 9: Run the tests**

Run: `taskset -c 0-3 make jstest && taskset -c 0-3 make test-web`
Expected: all pass — including
`test_the_palette_places_a_piece_and_evaluates_on_exit`, whose click-again
exit is retained.

- [ ] **Step 10: Drive all three gestures by hand**

Playwright's `drag_to` synthesises a clean gesture; a real pointer does not.
Open `http://127.0.0.1:8642/` and confirm by hand, recording what happened:

1. Drag a white rook from the palette onto d4 — it lands, **Done — evaluate**
   appears, and the rook stays armed so a second drop needs no return trip.
2. Press **Arrange**, then drag that rook from d4 to f6 — it moves, and no
   request is made.
3. Still in Arrange, drag it off the left edge — it disappears.
4. Press **Arrange** again — the board evaluates and leaves edit mode, the
   same way clicking an armed piece twice always has.
5. **Click** (do not drag) a palette piece — it arms, exactly as before, and
   clicking a square places. Confirm the click did not also start a drag.
6. While a piece is armed, press on an occupied square and move the pointer —
   nothing should be dragged; that gesture belongs to Arrange alone. This is
   the conflict the four-way arming exists to prevent, so see it not happen.
7. Press **Done — evaluate** — the position is evaluated and the button goes.
8. Repeat 1 with touch emulation if available.

Then screenshot the armed state in both themes and check the ink ring is
still unmistakable — it was invisible once already.

- [ ] **Step 11: Commit**

```bash
git add src/packages/web/helpmate_web/static/js/lib/board-edit.js \
        src/packages/web/helpmate_web/static/js/explorer.js \
        src/packages/web/helpmate_web/static/index.html \
        src/packages/web/helpmate_web/static/css/app.css \
        src/packages/web/tests/js/board-edit.test.js \
        src/packages/web/tests/ui/test_dashboard.py
git commit -m "feat(web): drag pieces into, around and off the board

Three gestures. Only the first needed new code: cm-chessboard raises the
other two natively and we were ignoring them. The hit test walks up from
elementFromPoint to the board's own data-square attributes rather than
doing geometry, so the coordinate frame and the orientation need no
arithmetic.

Click-to-arm is kept, not replaced -- drag is unreachable by keyboard and
awkward on touch. Edit mode gains a visible 'Done -- evaluate' exit,
which is also the one that works when the session began with a drag.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 10: Documentation, version, and the whole-branch gate

**Files:**
- Modify: `README.md`, `docs/USAGE.md`, `CHANGELOG.md`, `VERSION`
- Modify: `src/packages/api/pyproject.toml`, `src/packages/web/pyproject.toml`, `pyproject.toml`, `src/packages/bindings/pyproject.toml` (whichever carry a version), `src/packages/api/helpmate_server/__init__.py`, `src/packages/web/helpmate_web/__init__.py`

- [ ] **Step 1: Find every version string**

```bash
grep -rn "0\.10\.0" --include="*.toml" --include="*.py" --include="VERSION" \
  --include="*.md" --include="*.txt" . | grep -v CHANGELOG | grep -v "^./build/"
```

Every hit is a site to bump to `0.11.0`. **The trap:** `src/packages/api/pyproject.toml`
pins `helpmate>=0.10.0,<0.11`. Bumping only `version` there would leave the
API package excluding its own sibling. Bump the pin to `helpmate>=0.11.0,<0.12`
in the same edit.

- [ ] **Step 2: Bump them**

Set `0.11.0` everywhere the grep found, plus the dependency pin.

- [ ] **Step 3: Write the CHANGELOG entry**

Add at the top of `CHANGELOG.md`, matching the existing entries' shape:

```markdown
## 0.11.0

Dashboard UX: one skeleton for all three screens.

### Added
- Drag a piece from the palette onto the board, drag it to another square, or
  drag it off the board to remove it. Click-to-place is unchanged and remains
  the keyboard and touch path. Edit mode gains a visible **Done — evaluate**.
- The explorer shows the statistics of the table the position came from, in a
  band below the board and the move list.
- Materials lands on **All tables** — the whole corpus at once, including the
  materials that contain no helpmate and the generator versions that built the
  rest. The table list scrolls inside its rail, filters on substring, and is
  grouped by piece count.
- The search screen has a **Stop** button and shows elapsed time against the
  server's `--mine-timeout` budget.
- `GET /v1/stats` returns the corpus aggregate. `/v1/probe` and `/v1/moves`
  report the `material` whose table answered. `/v1/health` reports
  `mine_timeout`.

### Changed
- Every screen is a grey rail beside a white readout: grey is what you
  manipulate, white is what the tables say. No new colours — both surfaces are
  aliases over the existing palette.

### Fixed
- The board no longer overlaps the move list between 860px and ~1150px. It was
  sized from the viewport while its column was sized from the grid; at 960px
  that put a 460px board in a 368px column.
- A material with no helpmate said "longest mate h#127.5" — the stored
  `DTM_UNSOLVABLE` sentinel divided by two. 67 of the 295 tables in the
  reference corpus are in that state.
- A timed-out search reported "0 position(s) (truncated — raise max results
  for more)" instead of naming the timeout.
```

- [ ] **Step 4: Update the docs**

In `docs/USAGE.md`, in the dashboard section, document: the three drag
gestures and Done — evaluate; the per-table band; the Materials filter and All
tables; Stop and the elapsed counter (including that it does not free the
server's worker). In `README.md`, refresh the dashboard feature list to match.

Check the theme-toggle paragraph is still accurate after the header changes.

- [ ] **Step 5: Run the whole gate yourself**

Do not trust a reported result; run each and read its output.

```bash
taskset -c 0-3 make lint
taskset -c 0-3 make typecheck
taskset -c 0-3 make jstest
taskset -c 0-3 python -m pytest tests/repo -v
taskset -c 0-3 python -m pytest src/packages/api/tests -v
taskset -c 0-3 make test-web
taskset -c 0-3 make format-check
```

Expected: lint clean; typecheck clean; jstest exit 0; repo tests pass
(including the accent-confinement and theme-key guards); API tests pass; UI
tests pass with the new cases. Record the tail of each.

- [ ] **Step 6: Prove the accent guard still bites**

The CSS was substantially rewritten, so confirm the guard that protects it is
still capable of failing:

```bash
cp src/packages/web/helpmate_web/static/css/app.css /tmp/app.css.bak
printf '\n.move-group li.optimal { background: var(--accent); }\n' \
  >> src/packages/web/helpmate_web/static/css/app.css
taskset -c 0-3 python -m pytest tests/repo/test_accent_confined_to_focus_and_hover.py -v
cp /tmp/app.css.bak src/packages/web/helpmate_web/static/css/app.css
taskset -c 0-3 python -m pytest tests/repo/test_accent_confined_to_focus_and_hover.py -v
```

Expected: FAIL, then PASS. Record both.

- [ ] **Step 7: Look at every screen, both themes**

Six screenshots minimum: explorer / materials / search × light / dark, at
1280px, plus explorer at 420px and 960px. Check the rail is darker than the
readout in light mode and darker in dark mode too, that no control has become
invisible against its new surface, and that nothing scrolls sideways.

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "release: bump 0.10.0 -> 0.11.0 for the dashboard UX pass

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage**

| Spec section | Task |
|---|---|
| Rail and readout, tokens, tiles on the readout | 4 |
| Board sizing and centring | 4 |
| cm-chessboard retained; three drag gestures | 9 |
| Explicit edit exit, click-again retained | 9 |
| `squareFromTarget` pure module | 9 |
| Explorer statistics band; `material` from the API | 2, 6 |
| Shared renderer, `idPrefix` | 5 |
| Materials rail: scroll, filter, group | 7 |
| "All tables"; no-helpmate; generator spread | 3, 7 |
| `DTM_UNSOLVABLE` guard | 1 |
| `GET /v1/stats`, caching, missing sidecars | 3 |
| Honest timeout; Stop; `mine_timeout` on health | 2, 8 |
| Search form as rail | 8 |
| Non-goals (no build step, no cancellation, no format change) | Global Constraints |
| Verification (node / API / UI / screenshots) | every task, plus 10 |

**Type consistency** — `renderStats(box, stats, { idPrefix, samples })` is
defined in Task 5 and called with those exact option names in Tasks 5, 6 and
7. `aggregate_stats(sidecars, catalog)` is defined and called with that order
in Task 3. `api.overall()` is added in Task 7 Step 3 and used in Step 6 of the
same task. `hasHelpmate` / `mateLengthLabel` / `DTM_UNSOLVABLE` are exported
in Task 1 and imported in Tasks 5 and 7. `squareFromTarget` /
`exceedsDragThreshold` / `DRAG_THRESHOLD_PX` are exported in Task 9 Step 3 and
used in Step 8.

**Ordering** — Tasks 1-3 are independent and could run in any order. 4 must
precede 6, 7 and 8 (they apply `.rail` / `.readout`). 5 must precede 6 and 7.
2 must precede 6 and 8. 9 depends only on 4.

**Known risk carried deliberately** — Task 9's Step 10 is a manual check.
Playwright's `drag_to` synthesises a cleaner pointer sequence than a hand
does, so a passing suite is not proof the gesture feels right; the last cycle's
worst defect passed 27 tests and was found by looking.

**Defects found reviewing this plan against itself**, recorded so the same
mistakes are not made again in the briefs:

- Task 9 originally enabled click-to-place and drag-to-rearrange in the same
  mode. Both bind `pointerdown`, so dragging a piece away would have placed
  the armed piece first. Fixed by making arming four-way, one gesture per
  value — the same class of defect as the 0.10.0 cycle's "one replacement
  rule for two selectors whose defaults differed".
- Task 6's cache test counted every URL containing `/stats`, which also
  matches the corpus aggregate that `initMaterials()` requests on load — a
  race that would have made the test flaky rather than wrong.
- Task 8's `#mine-form` rule sets `background: var(--panel)` and an id
  selector outranks `.rail`, so replacing only the layout lines would have
  left the search rail white and quietly undone the split on one screen.
- Task 3's cache test asserted two identical responses, which passes whether
  or not a cache exists. Rewritten to add a table and require the count to
  change.
