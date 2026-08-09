"""Theme surfaces: the registry endpoint, theme filtering on mine, and
opt-in annotation on probe."""
import shutil
import subprocess

GOLDEN = "8/7k/5K2/8/8/8/8/6Q1 b - - 0 1"
# KQvk, count 160: the divergence class I-2 fixes (100 < count < 255). Any
# fixed sub-100 enumeration cap misses "closed-walk" here specifically.
COUNT_160 = "8/8/3Q4/8/k7/8/8/1K6 b - - 0 1"
# KQvk-shaped, dtm=12 count=255 (saturated): its optimal replies include a
# capture of the queen landing in Kvk, a material kqvk_only_dir deliberately
# lacks.
MISSING_SUBTABLE_FEN = "8/6kQ/8/8/8/8/8/K7 b - - 0 1"


def test_themes_endpoint_lists_the_registry(client):
    r = client.get("/v1/themes")
    assert r.status_code == 200
    body = r.json()
    names = [t["name"] for t in body["themes"]]
    assert "model" in names and "closed-walk" in names
    assert len(names) == len(set(names))
    for t in body["themes"]:
        assert t["doc"]          # every entry carries its definition


def test_themes_endpoint_reports_needs(client):
    # Task 10: /v1/themes returns helpmate.themes() verbatim, so `needs`
    # should flow through with no code change on this side -- confirmed here
    # rather than assumed.
    body = client.get("/v1/themes").json()
    assert all("needs" in t for t in body["themes"])


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


def test_probe_themes_missing_subtable_is_404_not_500(client_partial):
    # I-1 regression: solutions() (which theme detection forces) calls
    # value_of() on every legal child move, including a queen capture landing
    # in Kvk -- a material kqvk_only_dir deliberately lacks. A themes-less
    # probe of the same FEN, and /v1/line's all=true, both 404 on exactly
    # this kind of gap; probe?themes=true used to be the odd one out at 500.
    plain = client_partial.get("/v1/probe", params={"fen": MISSING_SUBTABLE_FEN})
    assert plain.status_code == 200
    r = client_partial.get("/v1/probe",
                           params={"fen": MISSING_SUBTABLE_FEN, "themes": "true"})
    assert r.status_code == 404, r.json()
    assert r.json()["error"]["code"] == "unknown_material"


def test_cli_and_api_agree_on_themes_above_100(kqvk_dir, client):
    # I-2 regression: the CLI caps enumeration at the position's own count;
    # the API used to always ask the binding for its fixed max=100 default.
    # For 100 < count < 255 that disagreed -- verified here with a KQvk
    # position whose count is 160 and whose themes include "closed-walk",
    # which a max=100 enumeration of this exact position drops (confirmed
    # manually: tb.themes(fen, max=100) omits it, tb.themes(fen) does not).
    helpmate_bin = shutil.which("helpmate")
    assert helpmate_bin, "the `helpmate` CLI binary must be on PATH (pip install .)"
    cli = subprocess.run(
        [helpmate_bin, "probe", COUNT_160, "--tables", str(kqvk_dir), "--themes"],
        capture_output=True, text=True, timeout=60)
    assert cli.returncode == 0, cli.stderr
    themes_line = next(line for line in cli.stdout.splitlines() if line.startswith("themes:"))
    cli_themes = set(themes_line.removeprefix("themes:").split())

    r = client.get("/v1/probe", params={"fen": COUNT_160, "themes": "true"})
    assert r.status_code == 200
    api_themes = set(r.json()["themes"])

    assert "closed-walk" in cli_themes
    assert cli_themes == api_themes
