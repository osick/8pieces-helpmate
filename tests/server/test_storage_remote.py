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
