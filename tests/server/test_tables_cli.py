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
    uploaded_manifest = json.loads(hub.store["manifest.json"])
    assert set(uploaded_manifest["files"]) == {"KQvk.hm", "KQvk.stats.json"}
    assert "Kvk.hm" not in uploaded_manifest["files"]   # never uploaded, not advertised
    local_manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert "Kvk.hm" in local_manifest["files"]          # local manifest covers the whole dir
    assert local_manifest["generator_version"] == "unknown"

def test_push_scoped_merges_with_existing_remote_manifest(tmp_path):
    seed(tmp_path)
    hub = RecorderHub()
    hub.store["manifest.json"] = json.dumps({
        "schema": 1, "generator_version": "old",
        "files": {"KRvk.hm": {"sha256": "deadbeef", "size": 42}},
    }).encode()
    rc = tables_cli.main(["push", "--tables", str(tmp_path), "--repo", "u/ds",
                          "--material", "KQvk"], hub_factory=lambda repo: hub)
    assert rc == 0
    uploaded_manifest = json.loads(hub.store["manifest.json"])
    assert uploaded_manifest["files"]["KRvk.hm"] == {"sha256": "deadbeef", "size": 42}
    assert set(uploaded_manifest["files"]) == {"KRvk.hm", "KQvk.hm", "KQvk.stats.json"}

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

class BrokenDownloadHub(RecorderHub):
    def download(self, filename: str, dest_dir: Path) -> Path:
        raise IOError(f"boom: {filename}")

def test_pull_handles_download_error(tmp_path, capsys):
    src, dst = tmp_path / "src", tmp_path / "dst"
    src.mkdir(); dst.mkdir(); seed(src)
    hub = RecorderHub()
    tables_cli.main(["push", "--tables", str(src), "--repo", "u/ds"],
                    hub_factory=lambda repo: hub)
    broken = BrokenDownloadHub()
    broken.store = hub.store
    rc = tables_cli.main(["pull", "--tables", str(dst), "--repo", "u/ds",
                          "--material", "KQvk"], hub_factory=lambda repo: broken)
    assert rc == 1
    captured = capsys.readouterr()
    assert "error:" in captured.err
    assert "Traceback" not in captured.err

def test_pull_defaults_to_all_materials(tmp_path):
    src, dst = tmp_path / "src", tmp_path / "dst"
    src.mkdir(); dst.mkdir(); seed(src)
    hub = RecorderHub()
    assert tables_cli.main(["push", "--tables", str(src), "--repo", "u/ds"],
                           hub_factory=lambda repo: hub) == 0
    rc = tables_cli.main(["pull", "--tables", str(dst), "--repo", "u/ds"],
                         hub_factory=lambda repo: hub)
    assert rc == 0
    assert (dst / "KQvk.hm").read_bytes() == b"\x03" * 24
    assert (dst / "KQvk.stats.json").exists()
    assert (dst / "Kvk.hm").read_bytes() == b"\x04" * 8
