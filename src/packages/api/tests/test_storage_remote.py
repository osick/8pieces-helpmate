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

def test_start_fetch_short_circuits_when_cached(tmp_path):
    src, cache = tmp_path / "hub", tmp_path / "cache"; src.mkdir(); cache.mkdir()
    seed(src)
    rs = RemoteSource(FakeHub(src), cache)
    rs.start_fetch("KRvk")
    wait_state(rs, "KRvk", "cached")
    original = (cache / "KRvk.hm").read_bytes()

    class LyingHub(FakeHub):
        def download(self, filename, dest_dir):
            p = super().download(filename, dest_dir)
            if filename.endswith(".hm"):
                p.write_bytes(b"\x02" * 32)   # would corrupt if re-fetched
            return p

    rs.hub = LyingHub(src)
    rs.start_fetch("KRvk")
    time.sleep(0.2)  # give a rogue re-fetch a chance to run
    assert rs.fetch_state("KRvk") == "cached"
    assert (cache / "KRvk.hm").read_bytes() == original

def test_fetch_cleans_up_both_files_on_stats_failure(tmp_path):
    src, cache = tmp_path / "hub", tmp_path / "cache"; src.mkdir(); cache.mkdir()
    seed(src)

    class StatsFailHub(FakeHub):
        def download(self, filename, dest_dir):
            if filename.endswith(".stats.json"):
                # simulate a download that writes a truncated file before
                # raising mid-transfer, so the orphan actually exists on disk
                (Path(dest_dir) / filename).write_text('{"trunc')
                raise IOError("boom mid-download")
            return super().download(filename, dest_dir)

    rs = RemoteSource(StatsFailHub(src), cache)
    rs.start_fetch("KRvk")
    wait_state(rs, "KRvk", "failed")
    assert not (cache / "KRvk.hm").exists()
    assert not (cache / "KRvk.stats.json").exists()

def test_fetch_state_rejects_wrong_size_cached_file(tmp_path):
    src, cache = tmp_path / "hub", tmp_path / "cache"; src.mkdir(); cache.mkdir()
    seed(src)
    (cache / "KRvk.hm").write_bytes(b"\x01" * 10)          # truncated: manifest says 32
    (cache / "KRvk.stats.json").write_text("{}")
    rs = RemoteSource(FakeHub(src), cache)
    assert rs.fetch_state("KRvk") == "absent"
    assert not (cache / "KRvk.hm").exists()
    assert not (cache / "KRvk.stats.json").exists()

def test_fetch_state_accepts_correct_size_cached_file(tmp_path):
    src, cache = tmp_path / "hub", tmp_path / "cache"; src.mkdir(); cache.mkdir()
    seed(src)
    (cache / "KRvk.hm").write_bytes(b"\x01" * 32)          # correct size, pre-existing
    rs = RemoteSource(FakeHub(src), cache)
    assert rs.fetch_state("KRvk") == "cached"
    assert (cache / "KRvk.hm").exists()

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
