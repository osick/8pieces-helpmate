GOLDEN = "8/7k/5K2/8/8/8/8/6Q1 b - - 0 1"

def test_moves_golden(client):
    r = client.get("/v1/moves", params={"fen": GOLDEN})
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["dtm"], body["count"], body["notation"]) == (2, 4, "h#1")

    by_san = {m["san"]: m for m in body["moves"]}
    assert {"Kh6", "Kh8"} <= set(by_san)
    # exactly the moves reaching dtm-1 are flagged optimal
    optimal = {m["san"] for m in body["moves"] if m["optimal"]}
    assert optimal == {"Kh6", "Kh8"}
    for san in optimal:
        assert by_san[san]["dtm"] == 1
        assert by_san[san]["solvable"] is True
        assert by_san[san]["notation"] == "h#0.5"
    # every move carries a resulting position and a uci
    for m in body["moves"]:
        assert m["fen"] and m["uci"]

def test_moves_of_a_mated_position_is_empty(client):
    r = client.get("/v1/moves", params={"fen": "8/8/8/8/8/8/8/kQK5 b - - 0 1"})
    assert r.status_code == 200
    assert r.json()["moves"] == []

def test_moves_invalid_fen_and_unknown_material(client):
    r = client.get("/v1/moves", params={"fen": "garbage"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_fen"
    r = client.get("/v1/moves", params={"fen": "1n2k3/8/8/8/8/8/8/QR2K3 b - - 0 1"})
    assert r.status_code == 404
    assert "helpmate gen" in r.json()["error"]["hint"]

def test_moves_missing_parameter(client):
    assert client.get("/v1/moves").status_code == 400
