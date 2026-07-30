# Storage + Read-Only API (v0.6) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A read-only FastAPI service serving probe/line/mine/stats/catalog from local and Hugging-Face-hosted tablebases, plus `helpmate-tables push/pull` sync tooling — spec: `docs/superpowers/specs/2026-07-30-storage-read-api-design.md`.

**Architecture:** Python-only layer on top of the existing `helpmate` pybind11 package (no C++ changes). `server/helpmate_server/` holds a storage layer (`TableSource` protocol: LocalDir → HF dataset chain with background fetch), a FastAPI app factory, and two console scripts. Tables are never committed to git; remote catalog = `manifest.json` in the HF dataset.

**Tech Stack:** FastAPI, uvicorn, huggingface_hub, pytest + FastAPI TestClient (httpx). Python ≥3.9.

## Global Constraints

- Read-only API: no POST/PUT/DELETE routes, ever (writes only via `helpmate-tables`).
- Existing `helpmate` package API is unchanged; bindings signatures: `Tablebase(dir)`, `.probe(fen) -> (dtm:int, count:int, flipped:bool) | None`, `.line(fen) -> list[str]`, `.lines(fen, max=100) -> list[list[str]]`, `.mine(mat, dtm, count, max) -> list[str]`, `.stats(mat) -> dict`, `helpmate.MissingTableError`, `helpmate.generate(mat, tables=..., threads=...) -> list[str]`.
- Error envelope everywhere: `{"error": {"code": str, "message": str, "hint": str|None}}`.
- Requests never block on a table download (6-piece ≈ 27 GB): remote-known-uncached → 202.
- Tests must not touch the network: the HF client is isolated behind `RemoteHub` and faked.
- Environment: dev box needs `PATH="$HOME/.local/bin:$PATH"`, `CXX=/usr/bin/g++-13 CC=/usr/bin/gcc-13`; editable install must reuse prefetched deps: `SKBUILD_CMAKE_ARGS="-DFETCHCONTENT_FULLY_DISCONNECTED=ON;-DFETCHCONTENT_SOURCE_DIR_CHESSMG=$PWD/build/_deps/chessmg-src;-DFETCHCONTENT_SOURCE_DIR_CATCH2=$PWD/build/_deps/catch2-src;-DFETCHCONTENT_SOURCE_DIR_JSON=$PWD/build/_deps/json-src" pip install -e ".[dev,server]"`. Never let a build clone from GitHub (SSH-passphrase popups). Tests run under `taskset -c 0-3`.
- Commits end with trailer: `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`; local commits, push only when the coordinator says so.

---

### Task 1: Package scaffolding (`[server]` extra, console scripts)

**Files:**
- Modify: `pyproject.toml`
- Create: `server/helpmate_server/__init__.py`
- Test: `tests/server/test_packaging.py`

**Interfaces:**
- Produces: importable `helpmate_server` package with `__version__`; extras `server`; scripts `helpmate-server`, `helpmate-tables` (targets implemented in Tasks 7/9 — stubs here).

- [ ] **Step 1: Write the failing test**

```python
# tests/server/test_packaging.py
def test_import_and_version():
    import helpmate_server
    assert helpmate_server.__version__ == "0.6.0.dev0"

def test_console_script_targets_exist():
    from helpmate_server.main import main as server_main
    from helpmate_server.tables_cli import main as tables_main
    assert callable(server_main) and callable(tables_main)
```

- [ ] **Step 2: Run it** — `taskset -c 0-3 python -m pytest tests/server/test_packaging.py -v` → FAIL (`ModuleNotFoundError: helpmate_server`).

- [ ] **Step 3: Implement**

`server/helpmate_server/__init__.py`:
```python
__version__ = "0.6.0.dev0"
```

`server/helpmate_server/main.py` (stub, replaced in Task 7):
```python
def main() -> None:
    raise SystemExit("helpmate-server: not implemented yet")
```

`server/helpmate_server/tables_cli.py` (stub, replaced in Task 9):
```python
def main() -> None:
    raise SystemExit("helpmate-tables: not implemented yet")
```

`pyproject.toml` — add/extend these sections (keep everything else):
```toml
[project.optional-dependencies]
dev = ["pytest", "chess>=1.10", "httpx"]
server = ["fastapi>=0.110", "uvicorn>=0.29", "huggingface_hub>=0.23"]

[project.scripts]
helpmate-server = "helpmate_server.main:main"
helpmate-tables = "helpmate_server.tables_cli:main"

[tool.scikit-build]
cmake.version = ">=3.24"
wheel.packages = ["python/helpmate", "server/helpmate_server"]
cmake.args = ["-DHELPMATE_PYTHON=ON"]
```

- [ ] **Step 4: Reinstall editable + run tests** — the Global Constraints `pip install -e ".[dev,server]"` command, then rerun Step 2 → PASS. Also `pip show helpmate | grep 0.5.0` still fine (package version stays 0.5.0 until release; `helpmate_server.__version__` tracks the server).

- [ ] **Step 5: Commit** — `git add pyproject.toml server/ tests/server/ && git commit` (`feat(server): package scaffolding for helpmate_server extra`).

---

### Task 2: Local storage — `SliceInfo` + `LocalDir` + `ChainSource`

**Files:**
- Create: `server/helpmate_server/storage.py`
- Test: `tests/server/test_storage_local.py`

**Interfaces:**
- Produces:
  - `@dataclass SliceInfo: material: str; pieces: int; size_bytes: int; max_dtm: int | None; cells: int | None; location: str` (location ∈ `"local" | "remote" | "cached"`)
  - `class LocalDir: __init__(self, path: str | Path); catalog(self) -> list[SliceInfo]; resolve(self, material: str) -> Path | None`
  - `class ChainSource: __init__(self, locals_: list[LocalDir], remote=None); catalog() -> list[SliceInfo]` (local wins on duplicates); `resolve(material) -> Path | None` (dir containing the `.hm`, first local hit); `status(material) -> tuple[str, object]` returning `("local", Path)` / `("unknown", None)` — remote states added in Task 4.

- [ ] **Step 1: Write the failing test**

```python
# tests/server/test_storage_local.py
import json
from pathlib import Path
from helpmate_server.storage import LocalDir, ChainSource, SliceInfo

def make_slice(d: Path, name: str, max_dtm=4, cells=100):
    (d / f"{name}.hm").write_bytes(b"\x00" * 16)
    (d / f"{name}.stats.json").write_text(json.dumps(
        {"material": name, "max_dtm": max_dtm, "plane_size": cells}))

def test_localdir_catalog_and_resolve(tmp_path):
    make_slice(tmp_path, "KQvk"); make_slice(tmp_path, "Kvk")
    src = LocalDir(tmp_path)
    cat = {s.material: s for s in src.catalog()}
    assert set(cat) == {"KQvk", "Kvk"}
    s = cat["KQvk"]
    assert (s.pieces, s.size_bytes, s.max_dtm, s.cells, s.location) == (3, 16, 4, 100, "local")
    assert src.resolve("KQvk") == tmp_path
    assert src.resolve("KRvk") is None

def test_localdir_missing_sidecar_still_listed(tmp_path):
    (tmp_path / "KRvk.hm").write_bytes(b"\x00" * 8)
    (s,) = LocalDir(tmp_path).catalog()
    assert (s.material, s.max_dtm, s.cells) == ("KRvk", None, None)

def test_chain_prefers_first_local(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"; a.mkdir(); b.mkdir()
    make_slice(a, "KQvk", max_dtm=4); make_slice(b, "KQvk", max_dtm=9); make_slice(b, "KRvk")
    chain = ChainSource([LocalDir(a), LocalDir(b)])
    cat = {s.material: s for s in chain.catalog()}
    assert cat["KQvk"].max_dtm == 4 and set(cat) == {"KQvk", "KRvk"}
    assert chain.resolve("KQvk") == a and chain.resolve("KRvk") == b
    assert chain.status("KQvk") == ("local", a)
    assert chain.status("KNvkqr") == ("unknown", None)
```

- [ ] **Step 2: Run it** — `taskset -c 0-3 python -m pytest tests/server/test_storage_local.py -v` → FAIL (import error).

- [ ] **Step 3: Implement `server/helpmate_server/storage.py`**

```python
from __future__ import annotations
import json
from dataclasses import dataclass
from pathlib import Path

@dataclass
class SliceInfo:
    material: str
    pieces: int
    size_bytes: int
    max_dtm: int | None
    cells: int | None
    location: str  # "local" | "remote" | "cached"

def _piece_count(material: str) -> int:
    return sum(1 for c in material if c != "v")

def _info_from_files(hm: Path, location: str) -> SliceInfo:
    material = hm.name[: -len(".hm")]
    max_dtm = cells = None
    sidecar = hm.with_name(material + ".stats.json")
    if sidecar.exists():
        s = json.loads(sidecar.read_text())
        max_dtm, cells = s.get("max_dtm"), s.get("plane_size")
    return SliceInfo(material, _piece_count(material), hm.stat().st_size,
                     max_dtm, cells, location)

class LocalDir:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def catalog(self) -> list[SliceInfo]:
        return sorted((_info_from_files(hm, "local")
                       for hm in self.path.glob("*.hm")),
                      key=lambda s: s.material)

    def resolve(self, material: str) -> Path | None:
        return self.path if (self.path / f"{material}.hm").exists() else None

class ChainSource:
    def __init__(self, locals_: list[LocalDir], remote=None):
        self.locals = locals_
        self.remote = remote  # Task 4

    def catalog(self) -> list[SliceInfo]:
        seen: dict[str, SliceInfo] = {}
        for src in self.locals:
            for s in src.catalog():
                seen.setdefault(s.material, s)
        if self.remote is not None:
            for s in self.remote.catalog():
                seen.setdefault(s.material, s)
        return sorted(seen.values(), key=lambda s: s.material)

    def resolve(self, material: str) -> Path | None:
        for src in self.locals:
            hit = src.resolve(material)
            if hit is not None:
                return hit
        return None

    def status(self, material: str):
        hit = self.resolve(material)
        if hit is not None:
            return ("local", hit)
        return ("unknown", None)  # remote states: Task 4
```

- [ ] **Step 4: Run it** → PASS. Run the whole server suite too: `taskset -c 0-3 python -m pytest tests/server -v`.

- [ ] **Step 5: Commit** — `feat(server): local storage layer (SliceInfo, LocalDir, ChainSource)`.

---

### Task 3: Manifest — sha256 build/verify

**Files:**
- Create: `server/helpmate_server/manifest.py`
- Test: `tests/server/test_manifest.py`

**Interfaces:**
- Produces: `sha256_file(path: Path) -> str`; `build_manifest(tables_dir: Path, generator_version: str) -> dict` (schema below); `write_manifest(tables_dir, generator_version) -> Path` (writes `manifest.json` in the dir); `verify_file(path: Path, manifest: dict) -> bool` (True iff listed and hash matches).
- Manifest schema: `{"schema": 1, "generator_version": str, "files": {"<name>": {"sha256": str, "size": int}}}` — `files` keys are file *names* (`KQvk.hm`, `KQvk.stats.json`), not paths.

- [ ] **Step 1: Write the failing test**

```python
# tests/server/test_manifest.py
import hashlib, json
from helpmate_server.manifest import sha256_file, build_manifest, write_manifest, verify_file

def test_build_and_verify(tmp_path):
    (tmp_path / "KQvk.hm").write_bytes(b"abc")
    (tmp_path / "KQvk.stats.json").write_text("{}")
    m = build_manifest(tmp_path, "0.5.0")
    assert m["schema"] == 1 and m["generator_version"] == "0.5.0"
    assert set(m["files"]) == {"KQvk.hm", "KQvk.stats.json"}
    assert m["files"]["KQvk.hm"]["sha256"] == hashlib.sha256(b"abc").hexdigest()
    assert m["files"]["KQvk.hm"]["size"] == 3
    p = write_manifest(tmp_path, "0.5.0")
    assert p.name == "manifest.json" and json.loads(p.read_text()) == m
    assert verify_file(tmp_path / "KQvk.hm", m) is True

def test_verify_rejects_corruption_and_unknown(tmp_path):
    (tmp_path / "KQvk.hm").write_bytes(b"abc")
    m = build_manifest(tmp_path, "0.5.0")
    (tmp_path / "KQvk.hm").write_bytes(b"abX")           # corrupt one byte
    assert verify_file(tmp_path / "KQvk.hm", m) is False
    assert verify_file(tmp_path / "other.hm", m) is False  # not listed
```

- [ ] **Step 2: Run it** → FAIL (import error).

- [ ] **Step 3: Implement `server/helpmate_server/manifest.py`**

```python
from __future__ import annotations
import hashlib, json
from pathlib import Path

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()

def build_manifest(tables_dir: Path, generator_version: str) -> dict:
    files = {}
    for pat in ("*.hm", "*.stats.json"):
        for p in sorted(Path(tables_dir).glob(pat)):
            files[p.name] = {"sha256": sha256_file(p), "size": p.stat().st_size}
    return {"schema": 1, "generator_version": generator_version, "files": files}

def write_manifest(tables_dir: Path, generator_version: str) -> Path:
    out = Path(tables_dir) / "manifest.json"
    out.write_text(json.dumps(build_manifest(tables_dir, generator_version),
                              indent=2, sort_keys=True))
    return out

def verify_file(path: Path, manifest: dict) -> bool:
    entry = manifest.get("files", {}).get(Path(path).name)
    return bool(entry) and sha256_file(path) == entry["sha256"]
```

- [ ] **Step 4: Run it** → PASS.

- [ ] **Step 5: Commit** — `feat(server): tables manifest (sha256 build/verify)`.

---

### Task 4: Remote backend — `RemoteHub` protocol, fake, HF implementation, fetch states

**Files:**
- Modify: `server/helpmate_server/storage.py`
- Test: `tests/server/test_storage_remote.py`

**Interfaces:**
- Consumes: Task 2 classes, Task 3 `verify_file`.
- Produces (in `storage.py`):
  - `RemoteHub` protocol: `fetch_manifest(self) -> dict` (the dataset's `manifest.json`); `download(self, filename: str, dest_dir: Path) -> Path`.
  - `class HFHub: __init__(self, repo_id: str)` implementing `RemoteHub` via `huggingface_hub` (`hf_hub_download(repo_id, filename, repo_type="dataset", local_dir=dest_dir)`); NOT unit-tested against the network — covered by manual acceptance.
  - `class RemoteSource: __init__(self, hub: RemoteHub, cache_dir: Path)`; `catalog() -> list[SliceInfo]` (from manifest, location `"remote"`, `max_dtm`/`cells` None, sizes from manifest); `start_fetch(material) -> None` (background thread downloads `.hm` + `.stats.json` to `cache_dir`, verifies via `verify_file`, deletes on mismatch); `fetch_state(material) -> str` ∈ `"absent" | "fetching" | "cached" | "failed"`.
  - `ChainSource.__init__(locals_, remote: RemoteSource | None)`; cache dir counts as an extra implicit LocalDir; `status()` now returns `("local", Path) | ("cached", Path) | ("fetching", None) | ("remote", SliceInfo) | ("failed", None) | ("unknown", None)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/server/test_storage_remote.py
import threading, time
from pathlib import Path
from helpmate_server.manifest import build_manifest
from helpmate_server.storage import LocalDir, ChainSource, RemoteSource

class FakeHub:
    """RemoteHub backed by a plain directory; optional gate blocks downloads."""
    def __init__(self, src_dir: Path, gate: threading.Event | None = None):
        self.src, self.gate = Path(src_dir), gate
    def fetch_manifest(self) -> dict:
        return build_manifest(self.src, "0.5.0")
    def download(self, filename: str, dest_dir: Path) -> Path:
        if self.gate is not None:
            assert self.gate.wait(5)
        dest = Path(dest_dir) / filename
        dest.write_bytes((self.src / filename).read_bytes())
        return dest

def seed(d: Path):
    (d / "KRvk.hm").write_bytes(b"\x01" * 32)
    (d / "KRvk.stats.json").write_text('{"material":"KRvk","max_dtm":14,"plane_size":29568}')

def wait_state(rs, material, want, timeout=5.0):
    t0 = time.time()
    while rs.fetch_state(material) != want:
        assert time.time() - t0 < timeout, f"never reached {want}"
        time.sleep(0.02)

def test_remote_catalog_and_fetch(tmp_path):
    src, cache = tmp_path / "hub", tmp_path / "cache"; src.mkdir(); cache.mkdir()
    seed(src)
    rs = RemoteSource(FakeHub(src), cache)
    (info,) = rs.catalog()
    assert (info.material, info.location, info.size_bytes) == ("KRvk", "remote", 32)
    assert rs.fetch_state("KRvk") == "absent"
    rs.start_fetch("KRvk")
    wait_state(rs, "KRvk", "cached")
    assert (cache / "KRvk.hm").read_bytes() == b"\x01" * 32

def test_fetching_state_visible_while_gated(tmp_path):
    src, cache = tmp_path / "hub", tmp_path / "cache"; src.mkdir(); cache.mkdir()
    seed(src); gate = threading.Event()
    rs = RemoteSource(FakeHub(src, gate), cache)
    rs.start_fetch("KRvk")
    wait_state(rs, "KRvk", "fetching")
    gate.set()
    wait_state(rs, "KRvk", "cached")

def test_corrupt_download_fails(tmp_path):
    src, cache = tmp_path / "hub", tmp_path / "cache"; src.mkdir(); cache.mkdir()
    seed(src)
    class LyingHub(FakeHub):
        def download(self, filename, dest_dir):
            p = super().download(filename, dest_dir)
            if filename.endswith(".hm"):
                p.write_bytes(b"\x02" * 32)   # corrupt after "transfer"
            return p
    rs = RemoteSource(LyingHub(src), cache)
    rs.start_fetch("KRvk")
    wait_state(rs, "KRvk", "failed")
    assert not (cache / "KRvk.hm").exists()

def test_chain_status_transitions(tmp_path):
    src, cache, loc = tmp_path / "hub", tmp_path / "cache", tmp_path / "loc"
    for d in (src, cache, loc): d.mkdir()
    seed(src)
    chain = ChainSource([LocalDir(loc)], RemoteSource(FakeHub(src), cache))
    kind, info = chain.status("KRvk")
    assert kind == "remote" and info.material == "KRvk"
    chain.remote.start_fetch("KRvk")
    wait_state(chain.remote, "KRvk", "cached")
    kind, path = chain.status("KRvk")
    assert kind == "cached" and path == cache
    assert chain.resolve("KRvk") == cache
    assert chain.status("KQRvkqr") == ("unknown", None)
```

- [ ] **Step 2: Run it** → FAIL (`RemoteSource` not defined).

- [ ] **Step 3: Implement** — append to `server/helpmate_server/storage.py`:

```python
import threading
from typing import Protocol
from .manifest import verify_file

class RemoteHub(Protocol):
    def fetch_manifest(self) -> dict: ...
    def download(self, filename: str, dest_dir: Path) -> Path: ...

class HFHub:
    """Hugging Face dataset hub. Network I/O only — kept thin, no unit tests
    (manual acceptance covers it)."""
    def __init__(self, repo_id: str):
        self.repo_id = repo_id
    def fetch_manifest(self) -> dict:
        import json as _json
        from huggingface_hub import hf_hub_download
        p = hf_hub_download(self.repo_id, "manifest.json", repo_type="dataset")
        return _json.loads(Path(p).read_text())
    def download(self, filename: str, dest_dir: Path) -> Path:
        from huggingface_hub import hf_hub_download
        p = hf_hub_download(self.repo_id, filename, repo_type="dataset",
                            local_dir=dest_dir)
        return Path(p)

class RemoteSource:
    def __init__(self, hub: RemoteHub, cache_dir: str | Path):
        self.hub = hub
        self.cache_dir = Path(cache_dir)
        self._manifest: dict | None = None
        self._states: dict[str, str] = {}
        self._lock = threading.Lock()

    def manifest(self) -> dict:
        if self._manifest is None:
            self._manifest = self.hub.fetch_manifest()
        return self._manifest

    def catalog(self) -> list[SliceInfo]:
        out = []
        for name, entry in self.manifest()["files"].items():
            if not name.endswith(".hm"):
                continue
            material = name[: -len(".hm")]
            out.append(SliceInfo(material, _piece_count(material),
                                 entry["size"], None, None, "remote"))
        return sorted(out, key=lambda s: s.material)

    def fetch_state(self, material: str) -> str:
        with self._lock:
            st = self._states.get(material)
        if st in ("fetching", "failed"):
            return st
        if (self.cache_dir / f"{material}.hm").exists():
            return "cached"
        return "absent"

    def start_fetch(self, material: str) -> None:
        with self._lock:
            if self._states.get(material) == "fetching":
                return
            self._states[material] = "fetching"
        threading.Thread(target=self._fetch, args=(material,), daemon=True).start()

    def _fetch(self, material: str) -> None:
        try:
            m = self.manifest()
            for name in (f"{material}.hm", f"{material}.stats.json"):
                if name not in m["files"]:
                    continue
                p = self.hub.download(name, self.cache_dir)
                if not verify_file(p, m):
                    p.unlink(missing_ok=True)
                    raise IOError(f"sha256 mismatch for {name}")
            with self._lock:
                self._states[material] = "done"
        except Exception:
            (self.cache_dir / f"{material}.hm").unlink(missing_ok=True)
            with self._lock:
                self._states[material] = "failed"
```

And replace `ChainSource.status` / extend `__init__` and `resolve`:

```python
class ChainSource:
    def __init__(self, locals_: list[LocalDir], remote: "RemoteSource | None" = None):
        self.locals = list(locals_)
        self.remote = remote

    # catalog() unchanged from Task 2 (remote branch now active)

    def resolve(self, material: str) -> Path | None:
        for src in self.locals:
            hit = src.resolve(material)
            if hit is not None:
                return hit
        if self.remote is not None and self.remote.fetch_state(material) == "cached":
            return self.remote.cache_dir
        return None

    def status(self, material: str):
        for src in self.locals:
            hit = src.resolve(material)
            if hit is not None:
                return ("local", hit)
        if self.remote is not None:
            st = self.remote.fetch_state(material)
            if st == "cached":
                return ("cached", self.remote.cache_dir)
            if st in ("fetching", "failed"):
                return (st, None)
            info = {s.material: s for s in self.remote.catalog()}.get(material)
            if info is not None:
                return ("remote", info)
        return ("unknown", None)
```

- [ ] **Step 4: Run it** → PASS (`taskset -c 0-3 python -m pytest tests/server -v` — Tasks 2/3 tests must stay green; note `_fetch` records `"done"` then `fetch_state` maps cached-on-disk → `"cached"`).

- [ ] **Step 5: Commit** — `feat(server): remote storage (RemoteHub protocol, HF hub, verified background fetch)`.

---

### Task 5: FastAPI app — health, catalog, stats, error envelope

**Files:**
- Create: `server/helpmate_server/app.py`
- Create: `tests/server/conftest.py`
- Test: `tests/server/test_api_catalog.py`

**Interfaces:**
- Consumes: `ChainSource` (Tasks 2/4), `helpmate.Tablebase`, `helpmate_server.__version__`.
- Produces: `create_app(chain: ChainSource, mine_cap: int = 1000, mine_timeout: float = 30.0) -> FastAPI` with routes `/v1/health`, `/v1/materials`, `/v1/materials/{name}/stats`; helper `error_json(code, message, hint=None) -> dict`; exceptions map: unknown → 404, invalid input → 400. CORS middleware `allow_origins=["*"]` (read-only API). Later tasks add routes to this same factory.

- [ ] **Step 1: Fixtures + failing test**

```python
# tests/server/conftest.py
import pytest, helpmate
from pathlib import Path
from fastapi.testclient import TestClient
from helpmate_server.storage import LocalDir, ChainSource
from helpmate_server.app import create_app

@pytest.fixture(scope="session")
def kqvk_dir(tmp_path_factory) -> Path:
    d = tmp_path_factory.mktemp("tables")
    helpmate.generate("KQvk", tables=str(d), threads=2)
    return Path(d)

@pytest.fixture()
def client(kqvk_dir) -> TestClient:
    app = create_app(ChainSource([LocalDir(kqvk_dir)]))
    return TestClient(app)
```

```python
# tests/server/test_api_catalog.py
def test_health(client):
    r = client.get("/v1/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok" and body["version"]
    assert body["tables_local"] == 2         # KQvk closure: KQvk + Kvk
    assert body["tables_remote"] == 0

def test_materials(client):
    r = client.get("/v1/materials")
    assert r.status_code == 200
    cat = {m["material"]: m for m in r.json()["materials"]}
    assert set(cat) == {"KQvk", "Kvk"}
    assert cat["KQvk"]["location"] == "local" and cat["KQvk"]["pieces"] == 3

def test_stats_ok_and_404(client):
    r = client.get("/v1/materials/KQvk/stats")
    assert r.status_code == 200 and r.json()["material"] == "KQvk"
    r = client.get("/v1/materials/KNvkqr/stats")
    assert r.status_code == 404
    err = r.json()["error"]
    assert err["code"] == "unknown_material" and "helpmate gen KNvkqr" in err["hint"]

def test_no_write_methods(client):
    for method in ("post", "put", "delete"):
        assert getattr(client, method)("/v1/materials").status_code == 405

def test_corrupt_table_500_envelope(tmp_path):
    from fastapi.testclient import TestClient
    from helpmate_server.storage import LocalDir, ChainSource
    from helpmate_server.app import create_app
    (tmp_path / "KQvk.hm").write_bytes(b"garbage")   # not a valid table file
    c = TestClient(create_app(ChainSource([LocalDir(tmp_path)])),
                   raise_server_exceptions=False)
    r = c.get("/v1/materials/KQvk/stats")
    assert r.status_code == 500
    assert r.json()["error"]["code"] == "internal"
```

- [ ] **Step 2: Run it** → FAIL (no `app` module). The `kqvk_dir` fixture itself must work (generate takes <1 s).

- [ ] **Step 3: Implement `server/helpmate_server/app.py`**

```python
from __future__ import annotations
import helpmate
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from . import __version__
from .storage import ChainSource

def error_json(code: str, message: str, hint: str | None = None) -> dict:
    return {"error": {"code": code, "message": message, "hint": hint}}

def _tb(chain: ChainSource, material_dir) -> helpmate.Tablebase:
    return helpmate.Tablebase(str(material_dir))

def create_app(chain: ChainSource, mine_cap: int = 1000,
               mine_timeout: float = 30.0) -> FastAPI:
    app = FastAPI(title="helpmate API", version=__version__)
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET"])

    @app.exception_handler(Exception)
    async def internal_error(request, exc):
        # Typed C++ errors (GeneratorLookupError etc.) carry material+FEN+cell
        # context in their message by design — surface it (spec: 500 + diagnostic).
        return JSONResponse(status_code=500,
                            content=error_json("internal", str(exc)))

    def unknown(material: str) -> JSONResponse:
        return JSONResponse(status_code=404, content=error_json(
            "unknown_material", f"no table for material '{material}'",
            hint=f"generate it with: helpmate gen {material} --tables <dir>"))

    @app.get("/v1/health")
    def health():
        cat = chain.catalog()
        return {"status": "ok", "version": __version__,
                "tables_local": sum(1 for s in cat if s.location in ("local", "cached")),
                "tables_remote": sum(1 for s in cat if s.location == "remote")}

    @app.get("/v1/materials")
    def materials():
        return {"materials": [vars(s) for s in chain.catalog()]}

    @app.get("/v1/materials/{name}/stats")
    def stats(name: str):
        d = chain.resolve(name)
        if d is None:
            return unknown(name)
        return _tb(chain, d).stats(name)

    return app
```

- [ ] **Step 4: Run it** → PASS (all of `tests/server`).

- [ ] **Step 5: Commit** — `feat(server): FastAPI app factory with health/catalog/stats`.

---

### Task 6: Probe and line endpoints (golden values)

**Files:**
- Modify: `server/helpmate_server/app.py`
- Test: `tests/server/test_api_probe.py`

**Interfaces:**
- Consumes: `create_app` (Task 5); bindings `probe/line/lines`; `helpmate.MissingTableError`.
- Produces: `GET /v1/probe?fen=` → 200 `{"dtm": int, "count": int, "flipped": bool, "notation": str}` | 200 `{"solvable": false}` for unsolvable | 400 invalid FEN | 404 no table; `GET /v1/line?fen=&all=false` → `{"lines": [[str]]}` (one line, or all optimal lines when `all=true`). h# notation rule: `dtm` plies, black-to-move even ⇒ `h#{dtm/2}` for even, `h#{(dtm+1)/2}.5`-style half-move for odd — copy the CLI's exact formatting from `src/cli/main.cpp` (`h_notation`).

- [ ] **Step 1: Write the failing test**

```python
# tests/server/test_api_probe.py
GOLD_FEN = "8/7k/5K2/8/8/8/8/6Q1 b - - 0 1"   # dtm=2 count=4 (Task 8 golden)

def test_probe_golden(client):
    r = client.get("/v1/probe", params={"fen": GOLD_FEN})
    assert r.status_code == 200
    b = r.json()
    assert (b["dtm"], b["count"], b["flipped"]) == (2, 4, False)
    assert b["notation"] == "h#1"

def test_probe_unsolvable_and_errors(client):
    kvk = "8/8/8/8/8/4k3/8/4K3 w - - 0 1"
    assert client.get("/v1/probe", params={"fen": kvk}).json() == {"solvable": False}
    assert client.get("/v1/probe", params={"fen": "garbage"}).status_code == 400
    knvkqr = "1n2k3/8/8/8/8/8/8/QR2K3 b - - 0 1"   # KNvkqr flipped-colors: no table
    assert client.get("/v1/probe", params={"fen": knvkqr}).status_code == 404

def test_line_first_and_all(client):
    r = client.get("/v1/line", params={"fen": GOLD_FEN})
    assert r.json()["lines"] == [["Kh6", "Qh2#"]]        # deterministic first line
    r = client.get("/v1/line", params={"fen": GOLD_FEN, "all": "true"})
    lines = r.json()["lines"]
    assert len(lines) == 4 and ["Kh6", "Qh2#"] in lines  # count=4 optimal lines
```

- [ ] **Step 2: Run it** → FAIL (404 route).

- [ ] **Step 3: Implement** — add inside `create_app` (after `stats`):

```python
    def _dir_for_fen(fen: str):
        # The FEN's board field determines the material, which names the table.
        board = fen.split()[0]
        white = "".join(sorted((c for c in board if c.isalpha() and c.isupper()),
                               key="KQRBNP".index))
        black = "".join(sorted((c.upper() for c in board if c.isalpha() and c.islower()),
                               key="KQRBNP".index))
        return white + "v" + black.lower()

    def h_notation(dtm: int) -> str:
        # dtm plies; black-to-move depths are even (h#n = 2n plies).
        return f"h#{dtm // 2}" if dtm % 2 == 0 else f"h#{dtm // 2}.5"

    @app.get("/v1/probe")
    def probe(fen: str):
        material = None
        try:
            material = _dir_for_fen(fen)
            d = chain.resolve(material) or chain.resolve(
                material.split("v")[1].upper() + "v" + material.split("v")[0].lower())
            if d is None:
                return unknown(material)
            res = _tb(chain, d).probe(fen)
        except helpmate.MissingTableError:
            return unknown(material or fen)
        except ValueError as e:
            return JSONResponse(status_code=400,
                                content=error_json("invalid_fen", str(e)))
        if res is None:
            return {"solvable": False}
        dtm, count, flipped = res
        return {"dtm": dtm, "count": count, "flipped": flipped,
                "notation": h_notation(dtm)}

    @app.get("/v1/line")
    def line(fen: str, all: bool = False):
        material = None
        try:
            material = _dir_for_fen(fen)
            d = chain.resolve(material)
            if d is None:
                return unknown(material)
            tb = _tb(chain, d)
            lines = tb.lines(fen) if all else [tb.line(fen)]
        except helpmate.MissingTableError:
            return unknown(material or fen)
        except ValueError as e:
            return JSONResponse(status_code=400,
                                content=error_json("invalid_fen", str(e)))
        return {"lines": lines}
```

**Note to implementer:** before finalizing `h_notation`, read `h_notation` in `src/cli/main.cpp` and confirm the API output matches the CLI exactly for BOTH parities (run `./build/helpmate probe` on the golden FEN and on a dtm=3 position obtained via `./build/helpmate mine KQvk --dtm 3 --max 1 --tables <scratch>`). If the CLI formats odd dtm differently than `h#{dtm//2}.5`, match the CLI and adjust the code above plus add the odd-parity assertion to the test.

- [ ] **Step 4: Run it** → PASS (whole `tests/server` suite).

- [ ] **Step 5: Commit** — `feat(server): probe and line endpoints with golden tests`.

---

### Task 7: Mine endpoint (cap, timeout, truncation) + `helpmate-server` entry point

**Files:**
- Modify: `server/helpmate_server/app.py`
- Modify: `server/helpmate_server/main.py` (replace stub)
- Test: `tests/server/test_api_mine.py`

**Interfaces:**
- Consumes: bindings `.mine(mat, dtm, count, max)`; `create_app(chain, mine_cap, mine_timeout)`.
- Produces: `GET /v1/mine?material=&dtm=&count=-1&max=100` → 200 `{"fens": [str], "truncated": bool}`; `max` clamped to `mine_cap`; timeout → 200 `{"fens": [], "truncated": true, "note": "timeout"}`. `main()` in `main.py`: argparse (`--tables` repeatable, `--hf-repo`, `--cache`, `--host 127.0.0.1`, `--port 8642`, `--mine-cap 1000`, `--mine-timeout 30`) → builds `ChainSource` → `uvicorn.run(app, host, port)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/server/test_api_mine.py
from fastapi.testclient import TestClient
from helpmate_server.storage import LocalDir, ChainSource
from helpmate_server.app import create_app

def test_mine_golden(client):
    r = client.get("/v1/mine", params={"material": "KQvk", "dtm": 2, "count": 1, "max": 5})
    assert r.status_code == 200
    b = r.json()
    # KQvk has more than 5 dtm=2/count=1 positions, so max=5 is truncated.
    assert len(b["fens"]) == 5 and b["truncated"] is True

def test_mine_exhausted_not_truncated(client):
    # Kvk is unsolvable everywhere: mining yields zero rows, nothing truncated.
    b = client.get("/v1/mine", params={"material": "Kvk", "dtm": 2}).json()
    assert b == {"fens": [], "truncated": False}

def test_mine_cap_clamps(kqvk_dir):
    app = create_app(ChainSource([LocalDir(kqvk_dir)]), mine_cap=3)
    c = TestClient(app)
    b = c.get("/v1/mine", params={"material": "KQvk", "dtm": 2, "max": 50}).json()
    assert len(b["fens"]) == 3 and b["truncated"] is True

def test_mine_timeout_truncates(kqvk_dir):
    app = create_app(ChainSource([LocalDir(kqvk_dir)]), mine_timeout=0.0)
    c = TestClient(app)
    b = c.get("/v1/mine", params={"material": "KQvk", "dtm": 2}).json()
    assert b == {"fens": [], "truncated": True, "note": "timeout"}

def test_mine_unknown_material(client):
    assert client.get("/v1/mine", params={"material": "KNvkqr", "dtm": 2}).status_code == 404

def test_server_main_builds(monkeypatch, kqvk_dir):
    import helpmate_server.main as m
    captured = {}
    monkeypatch.setattr(m, "_run", lambda app, host, port: captured.update(
        host=host, port=port, routes={r.path for r in app.routes}))
    m.main(["--tables", str(kqvk_dir), "--port", "9999"])
    assert captured["port"] == 9999 and "/v1/probe" in captured["routes"]
```

- [ ] **Step 2: Run it** → FAIL.

- [ ] **Step 3: Implement** — in `create_app` add:

```python
    from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutTimeout
    pool = ThreadPoolExecutor(max_workers=2)

    @app.get("/v1/mine")
    def mine(material: str, dtm: int, count: int = -1, max: int = 100):
        d = chain.resolve(material)
        if d is None:
            return unknown(material)
        clamped = min(max, mine_cap)
        fut = pool.submit(_tb(chain, d).mine, material, dtm, count, clamped + 1)
        try:
            fens = fut.result(timeout=mine_timeout)
        except FutTimeout:
            return {"fens": [], "truncated": True, "note": "timeout"}
        truncated = len(fens) > clamped
        return {"fens": fens[:clamped], "truncated": truncated}
```

(`clamped + 1` rows are requested so `truncated` means exactly "more rows existed than returned" — a full-but-exhausted result is not truncated.)

`server/helpmate_server/main.py`:
```python
from __future__ import annotations
import argparse
from .storage import LocalDir, ChainSource, RemoteSource, HFHub
from .app import create_app

def _run(app, host: str, port: int) -> None:
    import uvicorn
    uvicorn.run(app, host=host, port=port)

def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser("helpmate-server")
    p.add_argument("--tables", action="append", default=[], metavar="DIR")
    p.add_argument("--hf-repo", default=None)
    p.add_argument("--cache", default=None, metavar="DIR")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8642)
    p.add_argument("--mine-cap", type=int, default=1000)
    p.add_argument("--mine-timeout", type=float, default=30.0)
    a = p.parse_args(argv)
    remote = None
    if a.hf_repo:
        if not a.cache:
            p.error("--hf-repo requires --cache")
        remote = RemoteSource(HFHub(a.hf_repo), a.cache)
    chain = ChainSource([LocalDir(d) for d in a.tables], remote)
    _run(create_app(chain, a.mine_cap, a.mine_timeout), a.host, a.port)
```

- [ ] **Step 4: Run it** → PASS.

- [ ] **Step 5: Commit** — `feat(server): mine endpoint with cap/timeout + helpmate-server entry point`.

---

### Task 8: 202-fetching semantics for remote tables

**Files:**
- Modify: `server/helpmate_server/app.py`
- Test: `tests/server/test_api_fetching.py`

**Interfaces:**
- Consumes: `ChainSource.status()` states from Task 4; `FakeHub` pattern from `tests/server/test_storage_remote.py` (copy the class into the new test file — tests must be readable standalone).
- Produces: shared helper `_resolve_or_response(material) -> tuple[Path | None, JSONResponse | None]` used by stats/probe/line/mine: `local|cached` → path; `remote` → `start_fetch()` + 202 `{"status": "fetching", "material", "size_bytes"}`; `fetching` → 202 `{"status": "fetching", "material"}`; `failed` → 502 `error_json("fetch_failed", ...)`; `unknown` → the existing 404.

- [ ] **Step 1: Write the failing test**

```python
# tests/server/test_api_fetching.py
import json, threading, time
from pathlib import Path
from fastapi.testclient import TestClient
from helpmate_server.manifest import build_manifest
from helpmate_server.storage import LocalDir, ChainSource, RemoteSource
from helpmate_server.app import create_app

class FakeHub:
    def __init__(self, src_dir: Path, gate: threading.Event | None = None):
        self.src, self.gate = Path(src_dir), gate
    def fetch_manifest(self) -> dict:
        return build_manifest(self.src, "0.5.0")
    def download(self, filename: str, dest_dir: Path) -> Path:
        if self.gate is not None:
            assert self.gate.wait(5)
        dest = Path(dest_dir) / filename
        dest.write_bytes((self.src / filename).read_bytes())
        return dest

def test_remote_material_202_then_200(kqvk_dir, tmp_path):
    hub_dir, cache = tmp_path / "hub", tmp_path / "cache"
    hub_dir.mkdir(); cache.mkdir()
    for f in Path(kqvk_dir).glob("KQvk.*"):          # KQvk lives ONLY remotely
        (hub_dir / f.name).write_bytes(f.read_bytes())
    gate = threading.Event()
    chain = ChainSource([], RemoteSource(FakeHub(hub_dir, gate), cache))
    c = TestClient(create_app(chain))
    r = c.get("/v1/materials/KQvk/stats")
    assert r.status_code == 202 and r.json()["status"] == "fetching"
    gate.set()
    t0 = time.time()
    while r.status_code == 202:
        assert time.time() - t0 < 10
        time.sleep(0.05); r = c.get("/v1/materials/KQvk/stats")
    assert r.status_code == 200 and r.json()["material"] == "KQvk"

def test_unknown_still_404(kqvk_dir, tmp_path):
    cache = tmp_path / "cache"; cache.mkdir()
    hub_dir = tmp_path / "hub"; hub_dir.mkdir()
    (hub_dir / "manifest.json").write_text(json.dumps(
        {"schema": 1, "generator_version": "0.5.0", "files": {}}))
    chain = ChainSource([LocalDir(kqvk_dir)],
                        RemoteSource(FakeHub(hub_dir), cache))
    c = TestClient(create_app(chain))
    assert c.get("/v1/materials/KNvkqr/stats").status_code == 404
```

- [ ] **Step 2: Run it** → FAIL (stats returns 404 for remote-only material).

- [ ] **Step 3: Implement** — in `create_app`, add the helper and use it in `stats`, `probe`, `line`, `mine` (replace each route's `chain.resolve(...)` + `unknown(...)` pair):

```python
    def _resolve_or_response(material: str):
        kind, val = chain.status(material)
        if kind in ("local", "cached"):
            return val, None
        if kind == "remote":
            chain.remote.start_fetch(material)
            return None, JSONResponse(status_code=202, content={
                "status": "fetching", "material": material,
                "size_bytes": val.size_bytes})
        if kind == "fetching":
            return None, JSONResponse(status_code=202, content={
                "status": "fetching", "material": material})
        if kind == "failed":
            return None, JSONResponse(status_code=502, content=error_json(
                "fetch_failed", f"download of '{material}' failed",
                hint="check server logs; retry triggers a new download"))
        return None, unknown(material)
```

(No `RemoteSource` change needed for retries: its `start_fetch` guard only skips when a fetch is currently running, so a later call after `"failed"` starts a fresh download.)

- [ ] **Step 4: Run it** → PASS; full `tests/server` suite green (probe/line/mine tests from Tasks 6/7 must still pass with the refactored resolution).

- [ ] **Step 5: Commit** — `feat(server): 202-fetching semantics for remote-only tables`.

---

### Task 9: `helpmate-tables` push/pull CLI

**Files:**
- Modify: `server/helpmate_server/tables_cli.py` (replace stub)
- Test: `tests/server/test_tables_cli.py`

**Interfaces:**
- Consumes: `build_manifest`/`write_manifest` (Task 3), `HFHub` upload — new method `upload(self, files: list[Path], repo_id: str)` implemented with `huggingface_hub.HfApi.upload_file` (network, untested), injected as `hub_factory` for tests.
- Produces: CLI `helpmate-tables push --tables DIR --repo USER/DS [--material X ...]` (writes manifest.json locally, uploads selected `.hm` + `.stats.json` + manifest) and `helpmate-tables pull --repo USER/DS --tables DIR --material X ...` (downloads + sha256-verifies). `main(argv)` returns exit code (0 ok, 2 usage, 1 failure).

- [ ] **Step 1: Write the failing test**

```python
# tests/server/test_tables_cli.py
import json
from pathlib import Path
from helpmate_server import tables_cli

class RecorderHub:
    def __init__(self):
        self.uploaded: list[str] = []
        self.store: dict[str, bytes] = {}
    def upload(self, path: Path, repo_id: str) -> None:
        self.uploaded.append(path.name)
        self.store[path.name] = Path(path).read_bytes()
    def fetch_manifest(self) -> dict:
        return json.loads(self.store["manifest.json"])
    def download(self, filename: str, dest_dir: Path) -> Path:
        p = Path(dest_dir) / filename
        p.write_bytes(self.store[filename])
        return p

def seed(d: Path):
    (d / "KQvk.hm").write_bytes(b"\x03" * 24)
    (d / "KQvk.stats.json").write_text('{"material":"KQvk"}')
    (d / "Kvk.hm").write_bytes(b"\x04" * 8)

def test_push_selected_material(tmp_path):
    seed(tmp_path)
    hub = RecorderHub()
    rc = tables_cli.main(["push", "--tables", str(tmp_path), "--repo", "u/ds",
                          "--material", "KQvk"], hub_factory=lambda repo: hub)
    assert rc == 0
    assert set(hub.uploaded) == {"KQvk.hm", "KQvk.stats.json", "manifest.json"}
    m = json.loads((tmp_path / "manifest.json").read_text())
    assert "Kvk.hm" in m["files"]          # manifest covers the whole dir

def test_push_all_then_pull_roundtrip(tmp_path):
    src, dst = tmp_path / "src", tmp_path / "dst"
    src.mkdir(); dst.mkdir(); seed(src)
    hub = RecorderHub()
    assert tables_cli.main(["push", "--tables", str(src), "--repo", "u/ds"],
                           hub_factory=lambda repo: hub) == 0
    assert tables_cli.main(["pull", "--tables", str(dst), "--repo", "u/ds",
                            "--material", "KQvk"], hub_factory=lambda repo: hub) == 0
    assert (dst / "KQvk.hm").read_bytes() == b"\x03" * 24

def test_pull_rejects_corruption(tmp_path):
    src, dst = tmp_path / "src", tmp_path / "dst"
    src.mkdir(); dst.mkdir(); seed(src)
    hub = RecorderHub()
    tables_cli.main(["push", "--tables", str(src), "--repo", "u/ds"],
                    hub_factory=lambda repo: hub)
    hub.store["KQvk.hm"] = b"\x05" * 24                     # corrupt in transit
    rc = tables_cli.main(["pull", "--tables", str(dst), "--repo", "u/ds",
                          "--material", "KQvk"], hub_factory=lambda repo: hub)
    assert rc == 1 and not (dst / "KQvk.hm").exists()

def test_usage_errors():
    assert tables_cli.main([]) == 2
    assert tables_cli.main(["push", "--tables", "/nonexistent", "--repo", "u/ds"]) == 2
```

- [ ] **Step 2: Run it** → FAIL.

- [ ] **Step 3: Implement `server/helpmate_server/tables_cli.py`**

```python
from __future__ import annotations
import argparse, sys
from pathlib import Path
import helpmate  # for version stamp
from .manifest import write_manifest, verify_file

def _default_hub(repo_id: str):
    from .storage import HFHub
    hub = HFHub(repo_id)

    def upload(path: Path, repo: str) -> None:
        from huggingface_hub import HfApi
        HfApi().upload_file(path_or_fileobj=str(path), path_in_repo=path.name,
                            repo_id=repo, repo_type="dataset")
    hub.upload = lambda path, repo=repo_id: upload(path, repo)  # type: ignore[attr-defined]
    return hub

def main(argv: list[str] | None = None, hub_factory=_default_hub) -> int:
    p = argparse.ArgumentParser("helpmate-tables")
    sub = p.add_subparsers(dest="cmd")
    for name in ("push", "pull"):
        s = sub.add_parser(name)
        s.add_argument("--tables", required=True, metavar="DIR")
        s.add_argument("--repo", required=True, metavar="USER/DATASET")
        s.add_argument("--material", action="append", default=[])
    a = p.parse_args(argv)
    if a.cmd is None:
        p.print_usage()
        return 2
    tables = Path(a.tables)
    if not tables.is_dir():
        print(f"error: not a directory: {tables}", file=sys.stderr)
        return 2
    hub = hub_factory(a.repo)

    if a.cmd == "push":
        gen_version = "unknown"
        for sc in sorted(tables.glob("*.stats.json")):
            import json as _json
            gen_version = _json.loads(sc.read_text()).get("generator_version",
                                                          "unknown")
            break
        manifest_path = write_manifest(tables, generator_version=gen_version)
        names = a.material or sorted({f.name[: -len(".hm")]
                                      for f in tables.glob("*.hm")})
        for mat in names:
            for f in (tables / f"{mat}.hm", tables / f"{mat}.stats.json"):
                if f.exists():
                    hub.upload(f, a.repo)
                    print(f"pushed {f.name}")
        hub.upload(manifest_path, a.repo)
        print("pushed manifest.json")
        return 0

    # pull
    manifest = hub.fetch_manifest()
    for mat in a.material:
        for name in (f"{mat}.hm", f"{mat}.stats.json"):
            if name not in manifest["files"]:
                continue
            f = hub.download(name, tables)
            if not verify_file(f, manifest):
                f.unlink(missing_ok=True)
                print(f"error: sha256 mismatch for {name}", file=sys.stderr)
                return 1
            print(f"pulled {name}")
    return 0
```

**Note:** the test fixture's stats.json has no `generator_version`, so the manifest records `"unknown"` there — add `assert m["generator_version"] == "unknown"` to `test_push_selected_material`. Real tables carry it since v0.5.0.

- [ ] **Step 4: Run it** → PASS; whole `tests/server` suite green.

- [ ] **Step 5: Commit** — `feat(server): helpmate-tables push/pull with manifest verification`.

---

### Task 10: CI wiring, docs, changelog

**Files:**
- Modify: `.github/workflows/ci.yml` (python job)
- Modify: `README.md` (short "API server" section), `docs/USAGE.md` (full server section), `CHANGELOG.md`
- Test: CI runs `tests/server` (verified by reading the workflow + local dry run of the same commands)

**Interfaces:**
- Consumes: everything above.

- [ ] **Step 1: CI** — in `.github/workflows/ci.yml` python job, extend the install and test lines:

```yaml
      - run: pip install -e ".[dev,server]"
      - run: pytest tests/python tests/server -v
```

(Adjust to the job's existing step layout — keep its env/cmake setup unchanged. If the job currently installs `.[dev]`, replace that extra list; do not duplicate the install.)

- [ ] **Step 2: Docs** — `docs/USAGE.md`: append an "API server" section documenting: install (`pip install ".[server]"`), start (`helpmate-server --tables ~/myhelpmate/tables --hf-repo USER/DS --cache ~/.cache/helpmate-tables --port 8642`), every `/v1` route with one `curl` example each and example JSON (copy response shapes from the tests), the 202-fetching contract, mine cap/timeout, and `helpmate-tables push/pull` with the manifest format. `README.md`: 6-line section pointing to it. Every example must be run against a really-running local server first — paste real output.

- [ ] **Step 3: CHANGELOG** — under a new `## Unreleased` heading: server extra, storage layer + HF sync, API routes, 202 semantics.

- [ ] **Step 4: Verify** — `taskset -c 0-3 python -m pytest tests/python tests/server -v` (the exact CI line) → all green; boot the server once (`helpmate-server --tables <scratch KQvk dir>`) and `curl` the health + probe examples from the docs; paste outputs into the docs if they differ.

- [ ] **Step 5: Commit** — `docs+ci: server tests in CI, API usage documentation, changelog`.

---

## Verification checklist (whole plan)

- `taskset -c 0-3 python -m pytest tests/python tests/server -v` — green.
- C++ side untouched: `git diff --stat vs main` shows only `server/`, `tests/server/`, `pyproject.toml`, workflows, docs.
- Manual acceptance (coordinator, end of plan): serve the real `~/myhelpmate/tables`; browser-probe a 5-piece FEN; `helpmate-tables push` the 3-5-piece set to the real HF dataset (first real-network use); delete a local slice, probe → 202 → 200 from cache.
```
