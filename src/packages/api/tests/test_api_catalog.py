def test_health(client):
    r = client.get("/v1/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok" and body["version"]
    assert body["tables_local"] == 2         # KQvk closure: KQvk + Kvk
    assert body["tables_remote"] == 0

def test_materials(client):
    r = client.get("/v1/materials")
    assert r.status_code == 200
    cat = {m["material"]: m for m in r.json()["materials"]}
    assert set(cat) == {"KQvk", "Kvk"}
    assert cat["KQvk"]["location"] == "local" and cat["KQvk"]["pieces"] == 3

def test_stats_ok_and_404(client):
    r = client.get("/v1/materials/KQvk/stats")
    assert r.status_code == 200 and r.json()["material"] == "KQvk"
    r = client.get("/v1/materials/KNvkqr/stats")
    assert r.status_code == 404
    err = r.json()["error"]
    assert err["code"] == "unknown_material" and "helpmate gen KNvkqr" in err["hint"]

def test_no_write_methods(client):
    for method in ("post", "put", "delete"):
        r = getattr(client, method)("/v1/materials")
        assert r.status_code == 405
        assert r.json()["error"]["code"] == "method_not_allowed"

def test_unmatched_path_envelope(client):
    r = client.get("/v1/nonexistent")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"

def test_corrupt_table_500_envelope(tmp_path):
    from fastapi.testclient import TestClient
    from helpmate_server.storage import LocalDir, ChainSource
    from helpmate_server.app import create_app
    (tmp_path / "KQvk.hm").write_bytes(b"garbage")   # not a valid table file
    c = TestClient(create_app(ChainSource([LocalDir(tmp_path)])),
                   raise_server_exceptions=False)
    r = c.get("/v1/materials/KQvk/stats")
    assert r.status_code == 500
    assert r.json()["error"]["code"] == "internal"

def test_health_reports_the_mine_timeout_budget(client):
    # The search screen counts up against this budget, so it must not be a
    # number hardcoded in JavaScript.
    body = client.get("/v1/health").json()
    assert body["mine_timeout"] == 30.0
