"""CORS is opt-in per origin.

allow_origins=["*"] let any website read this API from a visitor's browser.
For a public read-only API that is a defensible choice, but it should be one
an operator makes, not the default they inherit."""
from fastapi.testclient import TestClient
from helpmate_server.storage import LocalDir, ChainSource
from helpmate_server.app import create_app


def test_no_cors_header_by_default(client):
    r = client.get("/v1/health", headers={"Origin": "https://evil.example"})
    assert r.status_code == 200
    assert "access-control-allow-origin" not in r.headers


def test_configured_origin_is_allowed(kqvk_dir):
    app = create_app(ChainSource([LocalDir(kqvk_dir)]),
                     cors_origins=["https://helpmate-tb.semantcon.org"])
    c = TestClient(app)
    r = c.get("/v1/health",
              headers={"Origin": "https://helpmate-tb.semantcon.org"})
    assert r.headers["access-control-allow-origin"] == \
        "https://helpmate-tb.semantcon.org"


def test_other_origins_stay_blocked_when_one_is_configured(kqvk_dir):
    app = create_app(ChainSource([LocalDir(kqvk_dir)]),
                     cors_origins=["https://helpmate-tb.semantcon.org"])
    c = TestClient(app)
    r = c.get("/v1/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in r.headers
