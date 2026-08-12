GOLD_FEN = "8/7k/5K2/8/8/8/8/6Q1 b - - 0 1"   # dtm=2 count=4 (Task 8 golden)

def test_probe_missing_fen_400_envelope(tmp_path):
    # Missing required query param triggers FastAPI's RequestValidationError,
    # which is NOT a StarletteHTTPException and must still get the envelope.
    from fastapi.testclient import TestClient
    from helpmate_server.storage import LocalDir, ChainSource
    from helpmate_server.app import create_app
    c = TestClient(create_app(ChainSource([LocalDir(tmp_path)])))
    r = c.get("/v1/probe")
    assert r.status_code == 400
    body = r.json()
    assert "detail" not in body
    assert body["error"]["code"] == "invalid_request"

def test_probe_empty_fen_400(tmp_path):
    from fastapi.testclient import TestClient
    from helpmate_server.storage import LocalDir, ChainSource
    from helpmate_server.app import create_app
    c = TestClient(create_app(ChainSource([LocalDir(tmp_path)])),
                   raise_server_exceptions=False)
    r = c.get("/v1/probe", params={"fen": ""})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "invalid_fen"

def test_probe_whitespace_fen_400(tmp_path):
    from fastapi.testclient import TestClient
    from helpmate_server.storage import LocalDir, ChainSource
    from helpmate_server.app import create_app
    c = TestClient(create_app(ChainSource([LocalDir(tmp_path)])),
                   raise_server_exceptions=False)
    r = c.get("/v1/probe", params={"fen": "   "})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "invalid_fen"

def test_probe_flip_fallback(client):
    # Color-flipped golden: white K, black k+q -> material Kvkq; direct
    # material has no table, but the flip to KQvk (the fixture's table)
    # resolves. Empirically verified via helpmate.Tablebase.probe: (2, 4, True).
    fen = "6q1/8/8/8/8/5k2/7K/8 w - - 0 1"
    r = client.get("/v1/probe", params={"fen": fen})
    assert r.status_code == 200
    b = r.json()
    assert (b["dtm"], b["count"], b["flipped"]) == (2, 4, True)
    assert b["notation"] == "h#1"

def test_probe_golden(client):
    r = client.get("/v1/probe", params={"fen": GOLD_FEN})
    assert r.status_code == 200
    b = r.json()
    assert (b["dtm"], b["count"], b["flipped"]) == (2, 4, False)
    assert b["notation"] == "h#1"

def test_probe_odd_dtm_notation(client):
    # dtm=3 (white-to-move) position, verified against the CLI (`helpmate mine
    # KQvk --dtm 3 --max 1` / `helpmate probe`): CLI prints "h#1.5" for this FEN.
    fen = "8/8/8/8/8/k7/8/1K1Q4 w - - 0 1"
    r = client.get("/v1/probe", params={"fen": fen})
    assert r.status_code == 200
    b = r.json()
    assert (b["dtm"], b["count"]) == (3, 1)
    assert b["notation"] == "h#1.5"

def test_probe_unsolvable_and_errors(client):
    kvk = "8/8/8/8/8/4k3/8/4K3 w - - 0 1"
    assert client.get("/v1/probe", params={"fen": kvk}).json() == {
        "solvable": False, "material": "Kvk"}
    assert client.get("/v1/probe", params={"fen": "garbage"}).status_code == 400
    knvkqr = "1n2k3/8/8/8/8/8/8/QR2K3 b - - 0 1"   # KNvkqr flipped-colors: no table
    assert client.get("/v1/probe", params={"fen": knvkqr}).status_code == 404

def test_line_first_and_all(client):
    r = client.get("/v1/line", params={"fen": GOLD_FEN})
    assert r.json()["lines"] == [["Kh6", "Qh2#"]]        # deterministic first line
    r = client.get("/v1/line", params={"fen": GOLD_FEN, "all": "true"})
    lines = r.json()["lines"]
    assert len(lines) == 4 and ["Kh6", "Qh2#"] in lines  # count=4 optimal lines

def test_probe_names_the_table_that_answered(client):
    r = client.get("/v1/probe", params={"fen": "8/7k/5K2/8/8/8/8/6Q1 b - - 0 1"})
    assert r.status_code == 200
    assert r.json()["material"] == "KQvk"


def test_probe_names_the_mirrored_table_when_colors_were_flipped(client):
    # Black holds the queen, so the position's own material is Kvkq and only
    # KQvk exists. probe() answers by flipping; the material it reports must
    # be the table that did the work, not the one the FEN spells out.
    r = client.get("/v1/probe", params={"fen": "8/7K/5k2/8/8/8/8/6q1 w - - 0 1"})
    assert r.status_code == 200
    body = r.json()
    assert body["flipped"] is True
    assert body["material"] == "KQvk"
