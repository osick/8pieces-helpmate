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
