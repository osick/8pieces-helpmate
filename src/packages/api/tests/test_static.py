import pytest
from fastapi.testclient import TestClient
from helpmate_server.app import create_app, _resolve_web_root
from helpmate_server.storage import ChainSource, LocalDir


# These two tests need a real dashboard to serve, which means the
# helpmate-web package (or the source checkout's fallback) resolving to a
# real directory. A real (non-editable) helpmate-api install with no
# helpmate-web present has nothing to serve: `_resolve_web_root(None)`
# returns None and `client` (built against a `serve_web=True` app) would 404
# rather than exercise the assertions below. They pass today only because
# every local install is editable and the source-checkout fallback rescues
# them -- a package must be independently verifiable without the rest of
# the repo, so skip rather than fail when the dashboard is genuinely absent.
def test_dashboard_is_served(client):
    if _resolve_web_root(None) is None:
        pytest.skip("helpmate-web not installed")
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    body = r.text
    for anchor in ("id=\"board\"", "id=\"fen-input\"", "id=\"move-list\"",
                   "id=\"material-list\"", "id=\"mine-form\""):
        assert anchor in body, anchor

def test_stylesheet_is_served(client):
    if _resolve_web_root(None) is None:
        pytest.skip("helpmate-web not installed")
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


# The three cases below exercise helpmate_server.main.main() itself, not
# create_app()/_resolve_web_root() directly -- they fail if --web-root/--no-web
# are removed from the CLI, or if the ValueError->parser.error() plumbing in
# main() is reverted, even though create_app()'s own behavior is unchanged.
# main() ends by blocking in uvicorn.run(); follow test_api_mine.py's
# test_server_main_builds and monkeypatch helpmate_server.main._run with a
# recorder instead of letting it start a real server.

def test_main_no_web_serves_no_dashboard(monkeypatch):
    import helpmate_server.main as m
    captured = {}
    monkeypatch.setattr(m, "_run", lambda app, host, port, limit_concurrency=None:
        captured.update(app=app))
    m.main(["--no-web"])
    c = TestClient(captured["app"])
    assert c.get("/").status_code == 404
    assert c.get("/v1/health").status_code == 200


def test_main_web_root_is_served(monkeypatch, tmp_path):
    import helpmate_server.main as m
    (tmp_path / "index.html").write_text("<p>custom-dashboard-marker</p>")
    captured = {}
    monkeypatch.setattr(m, "_run", lambda app, host, port, limit_concurrency=None:
        captured.update(app=app))
    m.main(["--web-root", str(tmp_path)])
    c = TestClient(captured["app"])
    r = c.get("/")
    assert r.status_code == 200
    assert "custom-dashboard-marker" in r.text


def test_main_web_root_not_a_directory_exits_via_parser_error(monkeypatch, tmp_path, capsys):
    import helpmate_server.main as m
    called = []
    monkeypatch.setattr(m, "_run", lambda app, host, port, limit_concurrency=None:
        called.append(True))
    missing = tmp_path / "nope"
    with pytest.raises(SystemExit) as excinfo:
        m.main(["--web-root", str(missing)])
    assert excinfo.value.code == 2
    # _run must never be reached, and the message must come from the
    # ValueError raised by _resolve_web_root (via parser.error), not from
    # argparse's own "unrecognized arguments" error or an unhandled traceback.
    assert called == []
    assert "not a directory" in capsys.readouterr().err
