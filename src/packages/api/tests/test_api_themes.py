"""Theme surfaces: the registry endpoint, theme filtering on mine, and
opt-in annotation on probe."""

GOLDEN = "8/7k/5K2/8/8/8/8/6Q1 b - - 0 1"


def test_themes_endpoint_lists_the_registry(client):
    r = client.get("/v1/themes")
    assert r.status_code == 200
    body = r.json()
    names = [t["name"] for t in body["themes"]]
    assert "model" in names and "closed-walk" in names
    assert len(names) == len(set(names))
    for t in body["themes"]:
        assert t["doc"]          # every entry carries its definition


def test_mine_accepts_a_repeatable_theme_parameter(client):
    r = client.get("/v1/mine", params={"material": "KQvk", "dtm": 2, "max": 5,
                                       "theme": ["mirror"]})
    assert r.status_code == 200
    assert "fens" in r.json()


def test_mine_theme_filter_actually_narrows(client):
    # KQvk dtm=2 true totals (measured): 580 unfiltered, 477 with theme
    # "mirror" -- max must exceed BOTH true totals, or comparing two
    # truncated-at-max lists would pass under any filter semantics, including
    # a no-op filter.
    wide = client.get("/v1/mine", params={"material": "KQvk", "dtm": 2, "max": 600}).json()
    narrow = client.get("/v1/mine", params={"material": "KQvk", "dtm": 2, "max": 600,
                                            "theme": ["mirror"]}).json()
    assert len(wide["fens"]) == 580 and len(narrow["fens"]) == 477
    assert len(narrow["fens"]) < len(wide["fens"])
    assert set(narrow["fens"]) <= set(wide["fens"])


def test_unknown_theme_is_a_400_naming_the_valid_ones(client):
    r = client.get("/v1/mine", params={"material": "KQvk", "dtm": 2,
                                       "theme": ["nosuchtheme"]})
    assert r.status_code == 400
    err = r.json()["error"]
    assert err["code"] == "invalid_theme"
    assert "model" in (err.get("hint") or "")


def test_one_bad_theme_rejects_the_whole_query(client):
    # The repeatable case: a valid name alongside an invalid one must still be
    # a 400 naming the bad one, in either order. Silently honouring the valid
    # half would answer a narrower question than was asked, which is the
    # failure mode the --end/--ends incident is named after.
    for params in ({"theme": ["mirror", "nosuchtheme"]},
                   {"theme": ["nosuchtheme", "mirror"]}):
        r = client.get("/v1/mine", params={"material": "KQvk", "dtm": 2, **params})
        assert r.status_code == 400, params
        assert r.json()["error"]["code"] == "invalid_theme"
        assert "nosuchtheme" in r.json()["error"]["message"]


def test_probe_omits_themes_unless_asked(client):
    assert "themes" not in client.get("/v1/probe", params={"fen": GOLDEN}).json()


def test_probe_themes_opt_in(client):
    body = client.get("/v1/probe", params={"fen": GOLDEN, "themes": "true"}).json()
    assert isinstance(body["themes"], list)


def test_probe_themes_on_flipped_position_is_200_not_500(client):
    # KQvk table only; this FEN is a KQvk-shaped goal but with colours swapped
    # (white king+black queen vs black king), so probe only answers it by
    # flipping colours to match the KQvk table. solutions()/themes() has no
    # such fallback and throws MissingTableError on the position as queried
    # (the exact bug the CLI hit in Task 6). The response must stay a valid
    # 200 with the flip reported as always, and "themes" must be distinguishable
    # from "no themes found" (i.e. not simply []).
    flipped_fen = "6q1/8/8/8/8/5k2/7K/8 w - - 0 1"
    r = client.get("/v1/probe", params={"fen": flipped_fen, "themes": "true"})
    assert r.status_code == 200
    body = r.json()
    assert body["flipped"] is True
    assert body["themes"] is None
    assert "themes_note" in body and "flip" in body["themes_note"].lower()
