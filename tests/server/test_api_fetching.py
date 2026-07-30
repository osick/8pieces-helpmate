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
