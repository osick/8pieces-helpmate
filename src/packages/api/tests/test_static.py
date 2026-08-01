import pytest
from fastapi.testclient import TestClient
from helpmate_server.app import create_app, _resolve_web_root
from helpmate_server.storage import ChainSource, LocalDir


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


# conftest.py provides `kqvk_dir` (a session-scoped Path holding a generated
# KQvk closure) and `client`; these cases need their own app, so they build
# one from kqvk_dir the same way the `client` fixture does.
def test_no_web_serves_no_dashboard(kqvk_dir):
    app = create_app(ChainSource([LocalDir(kqvk_dir)]), serve_web=False)
    c = TestClient(app)
    assert c.get("/").status_code == 404
    assert c.get("/v1/health").status_code == 200


def test_explicit_web_root_wins(tmp_path):
    (tmp_path / "index.html").write_text("<p>custom</p>")
    assert _resolve_web_root(str(tmp_path)) == tmp_path


def test_explicit_web_root_that_is_not_a_directory_is_an_error(tmp_path):
    with pytest.raises(ValueError, match="not a directory"):
        _resolve_web_root(str(tmp_path / "nope"))


def test_the_packaged_dashboard_is_found_by_import():
    helpmate_web = pytest.importorskip("helpmate_web")
    assert _resolve_web_root(None) == helpmate_web.static_dir()
