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

def test_failed_fetch_retries_on_next_request(kqvk_dir, tmp_path):
    # A material that failed to download must not stay wedged in "failed"
    # forever: the request that observes the failure (502 fetch_failed)
    # should itself re-trigger the download, so the *next* request already
    # sees "fetching" (202) and eventually succeeds (200) — making the
    # 502's hint ("retry triggers a new download") actually true.
    hub_dir, cache = tmp_path / "hub", tmp_path / "cache"
    hub_dir.mkdir(); cache.mkdir()
    for f in Path(kqvk_dir).glob("KQvk.*"):
        (hub_dir / f.name).write_bytes(f.read_bytes())

    class ToggleHub(FakeHub):
        """Fails every download while .fail is True; succeeds otherwise."""
        def __init__(self, src_dir):
            super().__init__(src_dir)
            self.fail = True
        def download(self, filename, dest_dir):
            if self.fail:
                raise IOError("boom")
            return super().download(filename, dest_dir)

    hub = ToggleHub(hub_dir)
    remote = RemoteSource(hub, cache)
    chain = ChainSource([], remote)

    # Drive the material to "failed" directly, as if a bad download had
    # already happened before any client asked for it.
    remote.start_fetch("KQvk")
    t0 = time.time()
    while remote.fetch_state("KQvk") != "failed":
        assert time.time() - t0 < 10
        time.sleep(0.02)

    c = TestClient(create_app(chain))
    hub.fail = False  # the retry the fix triggers should now succeed

    r = c.get("/v1/materials/KQvk/stats")
    assert r.status_code == 502
    assert r.json()["error"]["code"] == "fetch_failed"

    # This is the assertion that fails on unfixed code: today nothing
    # re-triggers start_fetch, so this would still be another 502.
    r = c.get("/v1/materials/KQvk/stats")
    assert r.status_code == 202 and r.json()["status"] == "fetching"

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
