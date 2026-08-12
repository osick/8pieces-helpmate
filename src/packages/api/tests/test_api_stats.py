"""Why this exists: the Materials screen's landing state summarises every
table at once, and the two facts most easily got wrong in a summary are the
ones a mixed corpus makes uncomfortable -- that 67 of 295 tables contain no
helpmate at all, and that seven different generator versions produced the
rest. A summary that quietly drops either is not shorter, it is wrong."""

from helpmate_server.aggregate import aggregate_stats
from helpmate_server.storage import SliceInfo


def _slice(material, pieces, size, location="local"):
    return SliceInfo(material, pieces, size, None, None, location)


KQVK = {
    "material": "KQvk", "max_dtm": 2, "plane_size": 100,
    "generator_version": "0.9.1",
    "cells": {"invalid": {"btm": 10, "wtm": 20}, "unsolvable": {"btm": 5, "wtm": 5}},
    "dtm_histogram": {"btm": {"2": 40}, "wtm": {"1": 60}},
    "uniqueness": {"btm": {"2": {"1": 30, "3": 10}}, "wtm": {"1": {"1": 60}}},
}
KBVK = {
    "material": "KBvk", "max_dtm": 255, "plane_size": 50,
    "generator_version": "0.6.1",
    "cells": {"invalid": {"btm": 30, "wtm": 40}, "unsolvable": {"btm": 20, "wtm": 10}},
    "dtm_histogram": {"btm": {}, "wtm": {}},
    "uniqueness": {"btm": {}, "wtm": {}},
}


def test_a_table_with_no_helpmate_is_named_not_ranked():
    agg = aggregate_stats([KQVK, KBVK],
                          [_slice("KQvk", 3, 700), _slice("KBvk", 3, 300)])
    assert agg["no_helpmate"] == ["KBvk"]
    assert agg["max_dtm"] == 2
    assert [d["material"] for d in agg["deepest"]] == ["KQvk"]


def test_sums_are_over_every_table():
    agg = aggregate_stats([KQVK, KBVK],
                          [_slice("KQvk", 3, 700), _slice("KBvk", 3, 300)])
    assert agg["tables"] == 2
    assert agg["size_bytes"] == 1000
    assert agg["tables_by_pieces"] == {"3": 2}
    # total = plane_size * 2 per table: (100 + 50) * 2
    assert agg["cells"]["total"] == 300
    assert agg["cells"]["invalid"] == 100      # 10+20+30+40
    assert agg["cells"]["unsolvable"] == 40    # 5+5+20+10
    assert agg["cells"]["solvable"] == 160
    assert agg["dtm_histogram"]["btm"] == {"2": 40}
    assert agg["dtm_histogram"]["wtm"] == {"1": 60}
    assert agg["generators"] == {"0.9.1": 1, "0.6.1": 1}


def test_uniqueness_is_collapsed_over_distance_under_one_key():
    # The per-distance breakdown does not survive aggregation -- the client
    # buckets over every distance anyway -- but the SHAPE must survive, so
    # lib/stats.js uniquenessBuckets() reads the aggregate unchanged.
    agg = aggregate_stats([KQVK], [_slice("KQvk", 3, 700)])
    assert list(agg["uniqueness"]["btm"]) == ["all"]
    assert agg["uniqueness"]["btm"]["all"] == {"1": 30, "3": 10}


def test_a_table_without_a_sidecar_is_counted_and_declared():
    # A remote-only table has no local sidecar. Counting it in `tables` while
    # excluding it from the sums under-reports silently unless we say so.
    agg = aggregate_stats([KQVK],
                          [_slice("KQvk", 3, 700), _slice("KRvkq", 4, 0, "remote")])
    assert agg["tables"] == 2
    assert agg["tables_without_stats"] == 1
    assert agg["tables_by_pieces"] == {"3": 1, "4": 1}


def test_the_endpoint_serves_the_aggregate(client):
    body = client.get("/v1/stats").json()
    assert body["tables"] >= 1
    assert "KQvk" in [d["material"] for d in body["deepest"]]
    assert body["cells"]["total"] > 0


def test_the_aggregate_is_recomputed_when_a_table_appears(kqvk_dir, tmp_path):
    # The cache is keyed on the catalog, so a newly generated or downloaded
    # table must invalidate it -- and nothing else may.
    from fastapi.testclient import TestClient
    from helpmate_server.storage import LocalDir, ChainSource
    from helpmate_server.app import create_app

    for ext in (".hm", ".stats.json"):
        (tmp_path / f"KQvk{ext}").write_bytes((kqvk_dir / f"KQvk{ext}").read_bytes())
    c = TestClient(create_app(ChainSource([LocalDir(tmp_path)])))

    first = c.get("/v1/stats").json()
    assert first["tables"] == 1
    assert c.get("/v1/stats").json() == first          # served from cache

    for ext in (".hm", ".stats.json"):
        (tmp_path / f"Kvk{ext}").write_bytes((kqvk_dir / f"Kvk{ext}").read_bytes())
    second = c.get("/v1/stats").json()
    assert second["tables"] == 2, "the catalog changed and the cache did not"
    assert second["no_helpmate"] == ["Kvk"]            # bare kings cannot mate


def test_the_aggregate_is_recomputed_when_a_sidecar_is_rewritten_in_place(kqvk_dir, tmp_path):
    # The higher-frequency real-world case: a corrected regeneration rewrites
    # only the .stats.json, leaving the .hm's name/size/location untouched.
    # A key built only from the catalog's .hm-derived fields cannot see this
    # -- it must be built from the sidecar's own identity too.
    import json

    from fastapi.testclient import TestClient
    from helpmate_server.storage import LocalDir, ChainSource
    from helpmate_server.app import create_app

    for ext in (".hm", ".stats.json"):
        (tmp_path / f"KQvk{ext}").write_bytes((kqvk_dir / f"KQvk{ext}").read_bytes())
    c = TestClient(create_app(ChainSource([LocalDir(tmp_path)])))

    first = c.get("/v1/stats").json()
    assert c.get("/v1/stats").json() == first          # served from cache

    assert first["max_dtm"] != 40   # sanity: distinct from the value written below

    sidecar_path = tmp_path / "KQvk.stats.json"
    sidecar = json.loads(sidecar_path.read_text())
    sidecar["max_dtm"] = 40         # still a real distance, well under the 255 sentinel
    sidecar_path.write_text(json.dumps(sidecar))

    second = c.get("/v1/stats").json()
    assert second["max_dtm"] == 40, "the sidecar changed in place and the cache did not"


def test_a_wrong_typed_max_dtm_is_a_missing_one_not_a_500():
    # A missing max_dtm already degrades ("this table has no helpmate"). A
    # sidecar that carries a string there -- a hand-edited file, a half-written
    # one, a future format -- must degrade the same way: int() letting the
    # ValueError out turned one bad table into a 500 for the whole summary.
    broken = {"material": "KXvk", "max_dtm": "deep", "plane_size": "lots",
              "cells": {"invalid": {"btm": "?"}, "unsolvable": {"wtm": None}},
              "dtm_histogram": {"btm": {"2": "many"}}}
    agg = aggregate_stats([KQVK, broken],
                          [_slice("KQvk", 3, 700), _slice("KXvk", 3, 300)])
    assert agg["no_helpmate"] == ["KXvk"]
    assert agg["max_dtm"] == 2                       # KQvk's, undisturbed
    assert [d["material"] for d in agg["deepest"]] == ["KQvk"]
    assert agg["cells"]["total"] == 200              # KQvk's plane_size * 2 only


def test_a_truncated_sidecar_degrades_to_no_stats_not_a_500(tmp_path):
    # An interrupted generation run leaves a half-written .stats.json next to
    # a .hm. docs/USAGE.md promises that costs that ONE table its stats; an
    # unguarded json.loads in _info_from_files made it a 500 for /v1/materials
    # AND /v1/stats, i.e. for the whole corpus, and chain.catalog() runs
    # before the guard /v1/stats had of its own.
    import json

    from fastapi.testclient import TestClient
    from helpmate_server.storage import LocalDir, ChainSource
    from helpmate_server.app import create_app

    good = {"material": "KQvk", "max_dtm": 4, "plane_size": 100,
            "generator_version": "0.11.0",
            "cells": {"invalid": {"btm": 1, "wtm": 1},
                      "unsolvable": {"btm": 1, "wtm": 1}},
            "dtm_histogram": {"btm": {"4": 10}, "wtm": {"3": 10}}}
    (tmp_path / "KQvk.hm").write_bytes(b"\x00" * 16)
    (tmp_path / "KQvk.stats.json").write_text(json.dumps(good))
    (tmp_path / "KRvk.hm").write_bytes(b"\x00" * 16)
    (tmp_path / "KRvk.stats.json").write_text(json.dumps(good)[:40])   # truncated

    c = TestClient(create_app(ChainSource([LocalDir(tmp_path)])),
                   raise_server_exceptions=False)

    mats = c.get("/v1/materials")
    assert mats.status_code == 200, mats.text
    cat = {m["material"]: m for m in mats.json()["materials"]}
    assert set(cat) == {"KQvk", "KRvk"}
    assert cat["KRvk"]["max_dtm"] is None and cat["KRvk"]["cells"] is None
    assert cat["KQvk"]["max_dtm"] == 4

    agg = c.get("/v1/stats")
    assert agg.status_code == 200, agg.text
    body = agg.json()
    assert body["tables"] == 2                 # counted...
    assert body["tables_without_stats"] == 1    # ...and declared unusable
    assert body["max_dtm"] == 4
