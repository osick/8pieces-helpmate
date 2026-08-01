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

def test_moves_uses_the_color_flip_fallback_like_probe(client):
    # Only the KQvk slice is generated, so a black-queen position resolves
    # through the flipped material and must say so.
    fen = "7K/8/8/8/8/8/8/k5q1 w - - 0 1"
    r = client.get("/v1/moves", params={"fen": fen})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["flipped"] is True
    assert body["dtm"] is not None and body["notation"].startswith("h#")
    p = client.get("/v1/probe", params={"fen": fen}).json()
    assert (body["dtm"], body["count"], body["flipped"]) == (p["dtm"], p["count"], p["flipped"])

def test_a_king_capture_is_reported_not_raised(client):
    # The position editor can build a position where the side NOT to move is
    # already in check; capturing that king is then a "legal move" leading
    # somewhere no tablebase can describe. That must not fail the whole
    # request with an invalid_fen naming a FEN the caller never sent --
    # /v1/probe answers this input, so /v1/moves has to as well.
    fen = "7k/8/8/8/8/8/8/K6Q w - - 0 1"
    assert client.get("/v1/probe", params={"fen": fen}).status_code == 200
    r = client.get("/v1/moves", params={"fen": fen})
    assert r.status_code == 200, r.text
    capture = [m for m in r.json()["moves"] if m["uci"] == "h1h8"]
    assert len(capture) == 1
    assert capture[0]["solvable"] is False
    assert capture[0]["dtm"] is None and capture[0]["optimal"] is False
