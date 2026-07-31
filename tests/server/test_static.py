def test_dashboard_is_served(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    body = r.text
    for anchor in ("id=\"board\"", "id=\"fen-input\"", "id=\"move-list\"",
                   "id=\"material-list\"", "id=\"mine-form\""):
        assert anchor in body, anchor

def test_stylesheet_is_served(client):
    r = client.get("/css/app.css")
    assert r.status_code == 200
    assert "text/css" in r.headers["content-type"]

def test_api_routes_still_win_over_static(client):
    # the static mount must not shadow /v1
    assert client.get("/v1/health").status_code == 200
