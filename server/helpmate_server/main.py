from __future__ import annotations
import argparse
from .storage import LocalDir, ChainSource, RemoteSource, HFHub
from .app import create_app

def _run(app, host: str, port: int) -> None:
    import uvicorn
    uvicorn.run(app, host=host, port=port)

def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser("helpmate-server")
    p.add_argument("--tables", action="append", default=[], metavar="DIR")
    p.add_argument("--hf-repo", default=None)
    p.add_argument("--cache", default=None, metavar="DIR")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8642)
    p.add_argument("--mine-cap", type=int, default=1000)
    p.add_argument("--mine-timeout", type=float, default=30.0)
    a = p.parse_args(argv)
    remote = None
    if a.hf_repo:
        if not a.cache:
            p.error("--hf-repo requires --cache")
        remote = RemoteSource(HFHub(a.hf_repo), a.cache)
    chain = ChainSource([LocalDir(d) for d in a.tables], remote)
    _run(create_app(chain, a.mine_cap, a.mine_timeout), a.host, a.port)
