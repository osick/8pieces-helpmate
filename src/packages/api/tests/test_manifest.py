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

def test_verify_missing_file_returns_false(tmp_path):
    (tmp_path / "KQvk.hm").write_bytes(b"abc")
    m = build_manifest(tmp_path, "0.5.0")
    (tmp_path / "KQvk.hm").unlink()  # simulate partially-downloaded/missing table
    assert verify_file(tmp_path / "KQvk.hm", m) is False
