import pytest, helpmate
from pathlib import Path
from fastapi.testclient import TestClient
from helpmate_server.storage import LocalDir, ChainSource
from helpmate_server.app import create_app

@pytest.fixture(scope="session")
def kqvk_dir(tmp_path_factory) -> Path:
    d = tmp_path_factory.mktemp("tables")
    helpmate.generate("KQvk", tables=str(d), threads=2)
    return Path(d)

@pytest.fixture()
def client(kqvk_dir) -> TestClient:
    app = create_app(ChainSource([LocalDir(kqvk_dir)]))
    return TestClient(app)

@pytest.fixture(scope="session")
def kqvk_only_dir(tmp_path_factory, kqvk_dir) -> Path:
    """KQvk.hm (+ sidecar) with NO Kvk.hm alongside it -- a partial table set,
    the routine (on-demand HF chain) shape that I-1 needs: KQvk itself is
    reachable, but a capture into Kvk is not. Copied out of kqvk_dir's full
    closure rather than generated fresh, so this stays cheap."""
    d = tmp_path_factory.mktemp("tables_kqvk_only")
    for ext in (".hm", ".stats.json"):
        (d / f"KQvk{ext}").write_bytes((kqvk_dir / f"KQvk{ext}").read_bytes())
    return Path(d)

@pytest.fixture()
def client_partial(kqvk_only_dir) -> TestClient:
    app = create_app(ChainSource([LocalDir(kqvk_only_dir)]))
    return TestClient(app)
