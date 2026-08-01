import os
import socket
import subprocess
import sys
import tempfile
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
    log = tempfile.TemporaryFile(mode="w+")
    p = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "--factory",
         "helpmate_server.main:_app_for_tests", "--port", str(port)],
        env={**os.environ, "HELPMATE_TABLES": tables},
        stdout=log, stderr=subprocess.STDOUT,
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
        p.wait()
        log.seek(0)
        output = log.read()
        log.close()
        raise RuntimeError(f"server did not start; output:\n{output}")
    yield url
    try:
        p.terminate()
        p.wait(timeout=10)
    except subprocess.TimeoutExpired:
        p.kill()
        p.wait()
    log.close()


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
