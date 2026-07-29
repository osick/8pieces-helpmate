import json, pathlib, pytest
import helpmate

@pytest.fixture(scope="session")
def tables(tmp_path_factory):
    d = str(tmp_path_factory.mktemp("tables"))
    written = helpmate.generate("KQvk", tables=d, threads=2)
    assert any(w.endswith("KQvk.hm") for w in written)
    return d

def test_probe_golden(tables):
    tb = helpmate.Tablebase(tables)
    # dtm/count golden per Task 8 (cross-checked against the cooperative oracle,
    # reconfirmed by tests/cpp/test_probe.cpp and the CLI's cli_probe test):
    # Black king has two legal replies (Kh6, Kh8); Kh6 allows three distinct
    # mates (Qg6#/Qh1#/Qh2#) and Kh8 allows one (Qg7#) -> count 4, not 1.
    assert tb.probe("8/7k/5K2/8/8/8/8/6Q1 b - - 0 1") == (2, 4, False)
    assert tb.probe("8/8/8/8/8/4k3/8/4K3 w - - 0 1") is None      # Kvk unsolvable

def test_line_and_mine(tables):
    tb = helpmate.Tablebase(tables)
    # Which of the 4 optimal lines line() finds first depends on legal_moves()
    # ordering (not part of the golden); it is deterministically "Kh6 Qh2#" for
    # this material/board (same as tests/cpp/test_probe.cpp and the CLI's
    # cli_line test).
    assert tb.line("8/7k/5K2/8/8/8/8/6Q1 b - - 0 1") == ["Kh6", "Qh2#"]
    fens = tb.mine("KQvk", dtm=2, count=1, max=5)
    assert len(fens) == 5
    for f in fens:
        assert tb.probe(f) == (2, 1, False)

def test_stats_dict(tables):
    tb = helpmate.Tablebase(tables)
    s = tb.stats("KQvk")
    assert s["material"] == "KQvk"
    assert s["max_dtm"] >= 3

def test_errors(tables):
    tb = helpmate.Tablebase(tables)
    with pytest.raises(ValueError):
        tb.probe("garbage")
    with pytest.raises(RuntimeError):
        tb.probe("8/8/8/8/3n4/4k3/8/4K3 w - - 0 1")   # Kvkn not generated
