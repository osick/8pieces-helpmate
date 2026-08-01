from __future__ import annotations
import argparse
import os
from .storage import LocalDir, ChainSource, RemoteSource, HFHub
from .app import create_app

def _run(app, host: str, port: int) -> None:
    import uvicorn
    uvicorn.run(app, host=host, port=port)

def _app_for_tests():
    # Factory for `uvicorn --factory helpmate_server.main:_app_for_tests`,
    # used by the browser test suite (src/packages/web/tests/ui) to serve a real
    # helpmate-server against a scratch tables dir named by the environment.
    tables = os.environ["HELPMATE_TABLES"]
    return create_app(ChainSource([LocalDir(tables)]))

def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser("helpmate-server")
    p.add_argument("--tables", action="append", default=[], metavar="DIR")
    p.add_argument("--hf-repo", default=None)
    p.add_argument("--cache", default=None, metavar="DIR")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8642)
    p.add_argument("--mine-cap", type=int, default=1000)
    p.add_argument("--mine-timeout", type=float, default=30.0)
    p.add_argument("--web-root", default=None, metavar="DIR",
                   help="serve the dashboard from DIR instead of the installed helpmate-web")
    p.add_argument("--no-web", action="store_true",
                   help="serve the API only, with no dashboard")
    a = p.parse_args(argv)
    remote = None
    if a.hf_repo:
        if not a.cache:
            p.error("--hf-repo requires --cache")
        remote = RemoteSource(HFHub(a.hf_repo), a.cache)
    chain = ChainSource([LocalDir(d) for d in a.tables], remote)
    try:
        app = create_app(chain, a.mine_cap, a.mine_timeout,
                         web_root=a.web_root, serve_web=not a.no_web)
    except ValueError as e:
        p.error(str(e))
    _run(app, a.host, a.port)
