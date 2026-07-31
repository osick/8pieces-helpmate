import os
import socket
import subprocess
import sys
import time
import urllib.request

import pytest
import helpmate


@pytest.fixture(scope="session")
def tables(tmp_path_factory):
    d = tmp_path_factory.mktemp("uitables")
    helpmate.generate("KQvk", tables=str(d), threads=2)
    return str(d)


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def server(tables):
    port = _free_port()
    p = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "--factory",
         "helpmate_server.main:_app_for_tests", "--port", str(port)],
        env={"HELPMATE_TABLES": tables, **os.environ},
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    url = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            urllib.request.urlopen(f"{url}/v1/health", timeout=1)
            break
        except Exception:
            time.sleep(0.1)
    else:
        p.kill()
        raise RuntimeError("server did not start")
    yield url
    p.terminate()
    p.wait(timeout=10)


@pytest.fixture(scope="session")
def browser():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        # --no-sandbox: user namespaces are restricted on the dev machine.
        b = pw.chromium.launch(args=["--no-sandbox"])
        yield b
        b.close()


@pytest.fixture()
def page(browser):
    ctx = browser.new_context()
    pg = ctx.new_page()
    yield pg
    ctx.close()
