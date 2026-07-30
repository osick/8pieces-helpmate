GOLD_FEN = "8/7k/5K2/8/8/8/8/6Q1 b - - 0 1"   # dtm=2 count=4 (Task 8 golden)

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
    assert client.get("/v1/probe", params={"fen": kvk}).json() == {"solvable": False}
    assert client.get("/v1/probe", params={"fen": "garbage"}).status_code == 400
    knvkqr = "1n2k3/8/8/8/8/8/8/QR2K3 b - - 0 1"   # KNvkqr flipped-colors: no table
    assert client.get("/v1/probe", params={"fen": knvkqr}).status_code == 404

def test_line_first_and_all(client):
    r = client.get("/v1/line", params={"fen": GOLD_FEN})
    assert r.json()["lines"] == [["Kh6", "Qh2#"]]        # deterministic first line
    r = client.get("/v1/line", params={"fen": GOLD_FEN, "all": "true"})
    lines = r.json()["lines"]
    assert len(lines) == 4 and ["Kh6", "Qh2#"] in lines  # count=4 optimal lines
