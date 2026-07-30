from fastapi.testclient import TestClient
from helpmate_server.storage import LocalDir, ChainSource
from helpmate_server.app import create_app

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
