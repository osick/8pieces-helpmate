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

def test_unsolvable_position_still_lists_its_moves(client):
    r = client.get("/v1/moves", params={"fen": "8/8/8/8/8/4k3/8/4K3 w - - 0 1"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["solvable"] is False
    assert len(body["moves"]) >= 2          # the list is NOT emptied for an unsolvable parent
    for m in body["moves"]:
        assert m["solvable"] is False and m["dtm"] is None and m["optimal"] is False
        assert m["san"] and m["uci"] and m["fen"]

def test_all_legal_moves_are_listed_not_only_optimal_ones(client):
    r = client.get("/v1/moves", params={"fen": "8/8/8/8/8/k7/8/1K2Q3 b - - 0 1"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["dtm"] == 4
    sans = [m["san"] for m in body["moves"]]
    assert len(sans) == 2      # every legal move, not a filtered subset
    optimal = [m for m in body["moves"] if m["optimal"]]
    suboptimal = [m for m in body["moves"] if m["solvable"] and not m["optimal"]]
    assert len(optimal) >= 1
    assert len(suboptimal) >= 1                          # solvable but not on a shortest path
    for m in suboptimal:
        assert m["dtm"] is not None and m["dtm"] != body["dtm"] - 1
