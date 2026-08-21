# ADR 0002: Presentation of the deepest-sound-problem showcase

Date: 2026-08-21
Status: accepted

## Context

`docs/DEEPEST.md` shows one position per material class: the deepest position
whose solution is unique. It is generated — `tools/deepest_showcase.py` reads
each table's `uniqueness` histogram and emits `docs/DEEPEST.json`,
`tools/render_deepest.py` renders that to markdown.

The first version had three presentation problems, and one gap:

- Positions linked to **lichess.org/analysis**. Lichess is a playing and
  analysis site for orthodox chess. It cannot solve a helpmate, does not
  understand `h#n` as a stipulation, and has no notion of a dual. The reader
  it sends away is a problemist, and it sends them somewhere that cannot
  answer the question the page just raised.
- Boards were drawn with **Unicode chess glyphs** (`♔♚`). They depend on the
  reader's font, collapse to tofu in a terminal, are nearly indistinguishable
  from each other at small sizes on a light background, and cannot be typed
  or grepped.
- Solutions were a **bare move list**, with no move numbers, so a 26-ply line
  had to be counted by hand to be read.
- There was **no print form**. The corpus is a body of previously uncomputed
  results, and the natural artefact for that is a booklet, not a 5,700-line
  markdown file.

## Decision

### Link to the Helpmate Analyzer

Positions link to `helpman.komtera.lt`, a solver and analyser built for
helpmates specifically. It takes the position and the stipulation, solves it,
and reports thematic content — which is the tool a reader of this page
actually wants.

The URL form is `?fen=<board field>&moves=<n|n.5>`, and both halves of that
are load-bearing:

- **The FEN is passed unencoded, board field only.** The site parses its own
  query string by hand: `transformToAssocArray()` splits on `&` and `=` and
  never calls `decodeURIComponent`. A percent-encoded FEN arrives at the board
  editor as a literal `%20` and does not load. The board field is
  `[A-Za-z0-9/]` only, so it needs no encoding at all.
- **Side to move is carried by the stipulation, not by the FEN.** The
  Analyzer's FEN field has no side-to-move component; `moves=13` is Black to
  play, which is the helpmate default, and `moves=8.5` is White. That is
  exactly the parity of our dtm, so it maps directly.

Both were verified against the live site rather than assumed.

### Popeye ASCII diagrams

Boards are drawn in the format Popeye emits: 37 columns, a `-` prefix marking
a black man, `S` for the knight, and a caption line carrying the stipulation
and the material count (`h#13` … `2 + 3`).

This is the notation the helpmate literature already uses, so it needs no
explanation to the audience. It is also pure ASCII: it survives a terminal, a
plain-text mail, a `grep`, and being read aloud, none of which the glyphs do.

Move lists are numbered in helpmate convention — Black moves first, so a
black-to-move problem opens `1.`, and an odd-depth one opens `1...` with
White's move.

The moves themselves stay in SAN as the solver emits them, `N` for the
knight and all. They are verbatim solver output and are the strings the
Analyzer accepts; rewriting them into `S` would mean parsing and
re-serialising a line this project did not compose.

### A LaTeX booklet as a second rendering

`tools/deepest_booklet.py` renders the same JSON to `docs/DEEPEST.tex`: an A5
booklet with real chess diagrams, a statistics chapter, one chapter per piece
count, and an index carrying page references.

Diagrams use the **`chessboard` package** (TeX Live: `texlive-games`) rather
than anything drawn by hand. It is the standard tool for the job, it ships
proper problemist diagram fonts, and inventing a board out of TikZ primitives
would produce something worse at more cost.

Everything that turns a row into something a reader sees — diagram, link,
notation, escaping — lives in `tools/deepest_lib.py`, imported by both
renderers, so the markdown and the booklet cannot drift apart.

### Coverage is counted against classes that can hold a mate

The booklet's scope is every 3–6 man material class. The plain combinatorial
count is 1,000 of them, but 125 have White with nothing but a bare king and
therefore cannot contain a mate under any circumstances. Excluding those
leaves **875**, and at six men that rule yields **645** — the same number
`README.md` and `docs/CONTRIBUTING-TABLES.md` already use for the six-piece
work. A test asserts the two agree, so the booklet and the README cannot
disagree about how much of the project is done.

## Consequences

- The booklet needs `chessboard.sty`, which is not in a minimal TeX Live.
  `make booklet` says so when it is missing, and the compile test skips
  rather than failing.
- `docs/DEEPEST.tex` is checked in and generated. Tests assert both it and
  `docs/DEEPEST.md` match what the renderers currently produce, so an edit to
  either file by hand fails CI instead of being silently overwritten later.
- `docs/DEEPEST.json` is now checked in as well. It was not, and when the
  presentation had to change the tables were not present in the checkout —
  the rendered markdown was the only surviving copy of the data and had to be
  parsed back. Keeping the JSON means re-rendering never needs a 38 GiB
  corpus again.
- The booklet is a **draft** and says so on its title page: 228 of 875
  classes, and only 7 of 645 at six men. Growing it is a re-run, not an edit.
- Anything added to the showcase's presentation belongs in `deepest_lib.py`.
  Adding it to one renderer only is how the two renderings start to disagree.
