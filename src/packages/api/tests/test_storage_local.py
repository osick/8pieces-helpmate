import json
from pathlib import Path
from helpmate_server.storage import LocalDir, ChainSource

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

def test_localdir_resolve_rejects_traversal(tmp_path):
    outside = tmp_path.parent / "x.hm"
    outside.write_bytes(b"\x00" * 8)
    try:
        assert LocalDir(tmp_path).resolve("../x") is None
    finally:
        outside.unlink(missing_ok=True)

def test_chain_prefers_first_local(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"; a.mkdir(); b.mkdir()
    make_slice(a, "KQvk", max_dtm=4); make_slice(b, "KQvk", max_dtm=9); make_slice(b, "KRvk")
    chain = ChainSource([LocalDir(a), LocalDir(b)])
    cat = {s.material: s for s in chain.catalog()}
    assert cat["KQvk"].max_dtm == 4 and set(cat) == {"KQvk", "KRvk"}
    assert chain.resolve("KQvk") == a and chain.resolve("KRvk") == b
    assert chain.status("KQvk") == ("local", a)
    assert chain.status("KNvkqr") == ("unknown", None)

def test_localdir_truncated_sidecar_is_listed_without_stats(tmp_path):
    # The unit under the endpoint test in test_api_stats.py: a sidecar left
    # half-written by an interrupted `helpmate gen` costs that table its
    # max_dtm/cells, exactly like a missing one, and nothing else.
    make_slice(tmp_path, "KQvk")
    (tmp_path / "KRvk.hm").write_bytes(b"\x00" * 8)
    (tmp_path / "KRvk.stats.json").write_text('{"material": "KRvk", "max_')
    cat = {s.material: s for s in LocalDir(tmp_path).catalog()}
    assert set(cat) == {"KQvk", "KRvk"}
    assert (cat["KRvk"].max_dtm, cat["KRvk"].cells) == (None, None)
    assert (cat["KQvk"].max_dtm, cat["KQvk"].cells) == (4, 100)

def test_localdir_sidecar_that_is_not_an_object_is_ignored(tmp_path):
    # json.loads succeeds and .get() then does not exist. Same degradation.
    (tmp_path / "KRvk.hm").write_bytes(b"\x00" * 8)
    (tmp_path / "KRvk.stats.json").write_text("[1, 2, 3]")
    (s,) = LocalDir(tmp_path).catalog()
    assert (s.material, s.max_dtm, s.cells) == ("KRvk", None, None)
