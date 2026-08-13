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
    # KPvk's own closure contains KQvk, KRvk, KBvk, KNvk and Kvk -- every
    # material the previous KQvk-only fixture ever produced -- so this is a
    # strict superset, not a swap. The extra cost (2.0s / 778 KB vs KQvk's
    # 0.4s / 175 KB, measured 2026-08-12) buys a pawn that can actually
    # promote, needed to exercise the promotion-dialog drag path (multiple
    # legal moves sharing one uci prefix) that no KQvk-only position can
    # reach -- a queen or rook never has more than one destination per
    # square.
    helpmate.generate("KPvk", tables=str(d), threads=2)
    return str(d)


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def empty_tables(tmp_path_factory):
    """A tables dir with nothing in it -- the state of every fresh install.

    The dashboard's first-run screen is not a hypothetical: it is what
    someone who has just installed the server and not yet generated a table
    sees, so it gets a fixture of its own rather than being reasoned about.
    """
    return str(tmp_path_factory.mktemp("uitables_empty"))


# A uvicorn serving the installed helpmate-server against `tables`, as a
# generator so each fixture below can `yield from` it: two session-scoped
# servers (a populated corpus and an empty one) with one copy of the
# start/wait/terminate dance between them.
def _serve(tables):
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
def server(tables):
    yield from _serve(tables)


@pytest.fixture(scope="session")
def empty_server(empty_tables):
    yield from _serve(empty_tables)


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
