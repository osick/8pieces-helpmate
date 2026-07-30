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
