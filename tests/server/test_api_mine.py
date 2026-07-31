from fastapi.testclient import TestClient
from helpmate_server.storage import LocalDir, ChainSource
from helpmate_server.app import create_app

# mine returns canonical (symmetry-reduced) FENs -- the golden position's
# canonical form; starts 2, ends 4.
GOLDEN = "8/8/8/8/8/2K5/7Q/1k6 b - - 0 1"

def test_mine_invalid_dtm_400_envelope(client):
    # Malformed query param (dtm not an int) triggers RequestValidationError,
    # which must still surface the contract's error envelope, not {"detail": ...}.
    r = client.get("/v1/mine", params={"material": "KQvk", "dtm": "notanint"})
    assert r.status_code == 400
    body = r.json()
    assert "detail" not in body
    assert body["error"]["code"] == "invalid_request"

def test_mine_material_traversal_rejected(tmp_path):
    # material=../secret/target must never be forwarded to the filesystem
    # layer: create the file it would resolve to and confirm the API refuses
    # it outright (400 invalid_material), not 404/500/200.
    tables = tmp_path / "tables"; tables.mkdir()
    secret = tmp_path / "secret"; secret.mkdir()
    (secret / "target.hm").write_bytes(b"\x00" * 8)
    c = TestClient(create_app(ChainSource([LocalDir(tables)])),
                   raise_server_exceptions=False)
    r = c.get("/v1/mine", params={"material": "../secret/target", "dtm": 2})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "invalid_material"

def test_mine_golden(client):
    r = client.get("/v1/mine", params={"material": "KQvk", "dtm": 2, "count": 1, "max": 5})
    assert r.status_code == 200
    b = r.json()
    # KQvk has more than 5 dtm=2/count=1 positions, so max=5 is truncated.
    assert len(b["fens"]) == 5 and b["truncated"] is True

def test_mine_exhausted_not_truncated(client):
    # Kvk is unsolvable everywhere: mining yields zero rows, nothing truncated.
    b = client.get("/v1/mine", params={"material": "Kvk", "dtm": 2}).json()
    assert b == {"fens": [], "truncated": False, "skipped_saturated": 0}

def test_mine_cap_clamps(kqvk_dir):
    app = create_app(ChainSource([LocalDir(kqvk_dir)]), mine_cap=3)
    c = TestClient(app)
    b = c.get("/v1/mine", params={"material": "KQvk", "dtm": 2, "max": 50}).json()
    assert len(b["fens"]) == 3 and b["truncated"] is True

def test_mine_timeout_truncates(kqvk_dir):
    app = create_app(ChainSource([LocalDir(kqvk_dir)]), mine_timeout=0.0)
    c = TestClient(app)
    b = c.get("/v1/mine", params={"material": "KQvk", "dtm": 2}).json()
    assert b == {"fens": [], "truncated": True, "note": "timeout", "skipped_saturated": 0}

def test_mine_unknown_material(client):
    assert client.get("/v1/mine", params={"material": "KNvkqr", "dtm": 2}).status_code == 404

def test_mine_shape_filters(client):
    r = client.get("/v1/mine", params={"material": "KQvk", "dtm": 2, "count": 4,
                                       "starts": 2, "ends": 4, "max": 200})
    assert r.status_code == 200
    body = r.json()
    assert GOLDEN in body["fens"]
    assert body["skipped_saturated"] == 0

    r = client.get("/v1/mine", params={"material": "KQvk", "dtm": 2, "count": 4,
                                       "starts": 3, "max": 200})
    assert r.status_code == 200 and GOLDEN not in r.json()["fens"]

def test_mine_shape_validation(client):
    r = client.get("/v1/mine", params={"material": "KQvk", "dtm": 2, "count": 2, "starts": 5})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "invalid_filter"

    r = client.get("/v1/mine", params={"material": "KQvk", "dtm": 2, "ends": 0})
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_filter"

def test_server_main_builds(monkeypatch, kqvk_dir):
    import helpmate_server.main as m
    captured = {}
    monkeypatch.setattr(m, "_run", lambda app, host, port: captured.update(
        host=host, port=port, routes={r.path for r in app.routes}))
    m.main(["--tables", str(kqvk_dir), "--port", "9999"])
    assert captured["port"] == 9999 and "/v1/probe" in captured["routes"]
