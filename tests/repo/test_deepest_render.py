"""The DEEPEST showcase renderers: diagram, links, notation, booklet.

docs/DEEPEST.md and docs/DEEPEST.tex are both generated from
docs/DEEPEST.json. Nothing in either file is hand-written, so the only place
their correctness can be asserted is here, against the renderers.

Three things are pinned down deliberately:

* the ASCII diagram is the Popeye board format, 37 columns wide, with `S` for
  the knight and `-` marking Black. Column drift is invisible in a diff of a
  5,700-line file, so the width is asserted line by line;
* the Helpmate Analyzer link. `helpman.komtera.lt` parses its query string by
  hand -- `transformToAssocArray()` splits on `&` and `=` and never calls
  `decodeURIComponent`, so a percent-encoded FEN arrives at the board editor
  as literal `%20`. The board field must therefore be passed raw;
* helpmate move numbering, where Black moves first. `h#n.5` starts at `1...`
  with a White move, and getting that backwards silently mislabels every
  odd-depth solution in the corpus.
"""
import importlib.util
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tools"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, TOOLS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod                     # deepest_lib imports by name
    spec.loader.exec_module(mod)
    return mod


sys.path.insert(0, str(TOOLS))
lib = _load("deepest_lib")
booklet = _load("deepest_booklet")

DATA = ROOT / "docs" / "DEEPEST.json"

# The position from the Popeye manual's diagram, used as the format reference:
# black king g8, white king c7, black knight c6, white pawn b3.
SAMPLE_FEN = "6k1/2K5/2n5/8/8/1P6/8/8 b - - 0 1"
SAMPLE_BOARD = """\
+---a---b---c---d---e---f---g---h---+
|                                   |
8   .   .   .   .   .   .  -K   .   8
|                                   |
7   .   .   K   .   .   .   .   .   7
|                                   |
6   .   .  -S   .   .   .   .   .   6
|                                   |
5   .   .   .   .   .   .   .   .   5
|                                   |
4   .   .   .   .   .   .   .   .   4
|                                   |
3   .   P   .   .   .   .   .   .   3
|                                   |
2   .   .   .   .   .   .   .   .   2
|                                   |
1   .   .   .   .   .   .   .   .   1
|                                   |
+---a---b---c---d---e---f---g---h---+"""


@pytest.fixture(scope="module")
def rows():
    assert DATA.exists(), f"{DATA} missing -- run tools/deepest_showcase.py"
    return json.loads(DATA.read_text())


# --------------------------------------------------------------------------
# depth notation


@pytest.mark.parametrize(
    "dtm,text", [(26, "h#13"), (17, "h#8.5"), (12, "h#6"), (1, "h#0.5"), (2, "h#1")]
)
def test_hn_names_the_half_move_case(dtm, text):
    assert lib.hn(dtm) == text


@pytest.mark.parametrize("dtm", range(1, 40))
def test_hn_round_trips_through_plies(dtm):
    assert lib.plies(lib.hn(dtm)) == dtm


# --------------------------------------------------------------------------
# the ASCII diagram


def test_board_matches_the_popeye_format():
    assert lib.board(SAMPLE_FEN) == SAMPLE_BOARD


def test_every_board_line_is_exactly_37_columns(rows):
    for r in rows:
        for line in lib.diagram(r["fen"], r["dtm"]).splitlines():
            assert len(line) == lib.BOARD_WIDTH, (r["material"], repr(line))


def test_knights_are_S_and_black_men_carry_a_minus():
    # -S for the black knight, S for a white one; nothing renders as N.
    assert "-S" in lib.board(SAMPLE_FEN)
    assert "N" not in lib.board(SAMPLE_FEN)
    white_knight = lib.board("8/8/8/8/8/8/8/N6k b - - 0 1")
    assert "   S" in white_knight and "-S" not in white_knight


def test_the_footer_carries_stipulation_and_material_count():
    footer = lib.diagram(SAMPLE_FEN, 18).splitlines()[-1]
    assert footer.startswith("  h#9")
    assert footer.endswith("2 + 2")             # K+P against k+n
    assert len(footer) == lib.BOARD_WIDTH


def test_footer_counts_both_sides_separately():
    # KBvkrp: two white men, three black.
    footer = lib.diagram("K7/8/3p4/8/8/2k5/8/5Br1 b - - 0 1", 26).splitlines()[-1]
    assert footer.endswith("2 + 3")
    assert "h#13" in footer


def test_diagram_is_the_board_plus_one_footer_line():
    d = lib.diagram(SAMPLE_FEN, 18).splitlines()
    assert "\n".join(d[:-1]) == SAMPLE_BOARD


# --------------------------------------------------------------------------
# the Helpmate Analyzer link


def test_helpman_url_passes_the_board_field_and_the_move_count():
    url = lib.helpman_url("K7/8/3p4/8/8/2k5/8/5Br1 b - - 0 1", 26)
    assert url == "https://helpman.komtera.lt/?fen=K7/8/3p4/8/8/2k5/8/5Br1&moves=13"


def test_helpman_url_uses_a_half_move_stipulation_when_white_starts():
    url = lib.helpman_url("8/8/8/8/8/2k5/8/K6R w - - 0 1", 17)
    assert url.endswith("&moves=8.5")


def test_helpman_url_is_never_percent_encoded(rows):
    # The site's own query parser does not decode; a %2F would reach the board
    # editor literally and the FEN would not load.
    for r in rows:
        assert "%" not in lib.helpman_url(r["fen"], r["dtm"])


def test_helpman_url_drops_the_side_to_move_field(rows):
    # Side to move is carried by moves=n vs moves=n.5, not by the FEN.
    for r in rows:
        assert " " not in lib.helpman_url(r["fen"], r["dtm"])


# --------------------------------------------------------------------------
# helpmate move numbering


def test_black_to_move_solutions_start_at_move_one():
    assert lib.numbered("d5 Kb7 d4 Kc6", 4) == "1.d5 Kb7 2.d4 Kc6"


def test_white_to_move_solutions_start_with_an_ellipsis():
    assert lib.numbered("Kb7 d4 Kc6", 3) == "1...Kb7 2.d4 Kc6"


def test_numbering_preserves_every_move(rows):
    for r in rows:
        moves = r["solution"].split()
        out = lib.numbered(r["solution"], r["dtm"])
        assert re.sub(r"\d+\.(\.\.)?", "", out).split() == moves


def test_solution_length_equals_the_depth(rows):
    for r in rows:
        assert len(r["solution"].split()) == r["dtm"], r["material"]


# --------------------------------------------------------------------------
# the rendered markdown


@pytest.fixture(scope="module")
def markdown():
    return (ROOT / "docs" / "DEEPEST.md").read_text()


def test_markdown_links_to_the_helpmate_analyzer(markdown):
    assert "helpman.komtera.lt" in markdown


def test_markdown_no_longer_links_to_lichess(markdown):
    assert "lichess.org" not in markdown


def test_markdown_has_one_helpman_link_per_class(markdown, rows):
    assert markdown.count("https://helpman.komtera.lt/?fen=") == len(rows)


def test_markdown_uses_the_ascii_diagram(markdown):
    assert "+---a---b---c---d---e---f---g---h---+" in markdown
    assert "♔" not in markdown and "♚" not in markdown


def test_markdown_is_what_the_renderer_produces(tmp_path, markdown):
    out = tmp_path / "DEEPEST.md"
    subprocess.run(
        [sys.executable, str(TOOLS / "render_deepest.py"),
         "--data", str(DATA), "--out", str(out)],
        check=True, capture_output=True,
    )
    assert out.read_text() == markdown, "docs/DEEPEST.md is stale"


# --------------------------------------------------------------------------
# the booklet


def test_latex_escapes_the_hash_in_a_stipulation():
    assert lib.tex_escape("h#13") == "h\\#13"
    assert lib.tex_escape("a_b & c%") == "a\\_b \\& c\\%"


@pytest.fixture(scope="module")
def tex(rows):
    return booklet.build(rows)


def test_booklet_is_a_compilable_document(tex):
    assert tex.startswith("%")                  # provenance banner
    assert "\\documentclass" in tex
    assert tex.rstrip().endswith("\\end{document}")


def test_booklet_draws_boards_with_the_chessboard_package(tex):
    assert "\\usepackage{chessboard}" in tex
    assert "\\chessboard[" in tex


def test_booklet_has_one_diagram_per_class(tex, rows):
    assert tex.count("\\hmentry{") == len(rows)
    for r in rows:
        assert r["fen"] in tex, r["material"]


def test_booklet_covers_every_piece_count_present(tex, rows):
    for n in sorted({r["pieces"] for r in rows}):
        assert booklet.CHAPTERS[n] in tex


def test_booklet_reports_the_corpus_size(tex, rows):
    s = booklet.statistics(rows)
    assert s["classes"] == len(rows)
    assert f"{s['classes']}" in tex
    assert f"{s['indexed']:,}".replace(",", "\\,") in tex


def test_booklet_coverage_is_measured_against_the_full_enumeration():
    # 3..6 men: white K plus 0..4 officers, black k plus the rest.
    assert booklet.possible_classes(3) == 10
    assert booklet.possible_classes(4) == 55
    assert booklet.possible_classes(5) == 220
    assert booklet.possible_classes(6) == 715


@pytest.mark.parametrize("pieces,n", [(3, 5), (4, 40), (5, 185), (6, 645)])
def test_booklet_excludes_classes_that_cannot_hold_a_mate(pieces, n):
    # A bare white king can never mate, so those classes hold no problem.
    assert booklet.mateable_classes(pieces) == n


def test_six_man_count_agrees_with_the_repo():
    # README.md and docs/CONTRIBUTING-TABLES.md both put the six-piece work at
    # 645 classes. The booklet's denominator has to be the same number, or the
    # two documents disagree about how much of the project is done.
    readme = (ROOT / "README.md").read_text()
    assert f"| 6 | {booklet.mateable_classes(6)} |" in readme


def test_booklet_declares_itself_a_draft(tex, rows):
    s = booklet.statistics(rows)
    assert "draft" in tex.lower()
    assert s["classes"] < s["possible"]         # the reason it is a draft


def test_booklet_links_to_the_helpmate_analyzer(tex, rows):
    assert tex.count("helpman.komtera.lt") >= len(rows)


def test_booklet_escapes_every_stipulation(tex):
    # A bare # in LaTeX is a macro parameter, so an unescaped h#13 in the body
    # either aborts the run or silently eats the next token. The preamble is
    # exempt: #1..#7 there are \hmentry's own parameters.
    body = tex.split(booklet.PREAMBLE, 1)[1]
    for line in body.splitlines():
        if line.lstrip().startswith("%"):
            continue
        for m in re.finditer(r"#", line):
            assert line[m.start() - 1] == "\\", line


def test_checked_in_booklet_is_not_stale(tex):
    assert (ROOT / "docs" / "DEEPEST.tex").read_text() == tex


@pytest.mark.skipif(shutil.which("pdflatex") is None, reason="no pdflatex")
@pytest.mark.skipif(
    subprocess.run(["kpsewhich", "chessboard.sty"], capture_output=True).returncode != 0,
    reason="chessboard.sty not installed (TeX Live: texlive-games)",
)
def test_booklet_compiles(tmp_path, tex):
    src = tmp_path / "DEEPEST.tex"
    src.write_text(tex)
    for _ in range(2):                          # toc + refs need two passes
        p = subprocess.run(
            ["pdflatex", "-interaction=nonstopmode", "-halt-on-error", src.name],
            cwd=tmp_path, capture_output=True, text=True,
        )
    assert p.returncode == 0, p.stdout[-3000:]
    assert (tmp_path / "DEEPEST.pdf").stat().st_size > 100_000
