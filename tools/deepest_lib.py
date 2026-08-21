"""Shared presentation for the DEEPEST showcase: diagrams, links, notation.

Both renderers -- `render_deepest.py` (markdown) and `deepest_booklet.py`
(LaTeX) -- read the same `docs/DEEPEST.json` and must present the same
position the same way, so everything that turns a row into something a reader
sees lives here.
"""
from __future__ import annotations

# Popeye's diagram is 37 columns: a rank digit, eight four-column cells, and
# the rank digit again. Every line of a diagram is padded to this.
BOARD_WIDTH = 37

# Problem-chess piece letters. The knight is S (Springer) -- N is the German
# Nachtreiter, and the whole helpmate literature, Popeye included, writes S.
LETTER = {"K": "K", "Q": "Q", "R": "R", "B": "B", "N": "S", "P": "P"}

FILES = "abcdefgh"


def hn(dtm: int) -> str:
    """`h#n` from a ply distance. Odd dtm means White to move: the .5 case."""
    return f"h#{dtm // 2}" if dtm % 2 == 0 else f"h#{dtm // 2}.5"


def plies(stipulation: str) -> int:
    """Inverse of `hn`: `h#8.5` -> 17."""
    body = stipulation[2:]
    whole, _, half = body.partition(".")
    return int(whole) * 2 + (1 if half else 0)


def moves_param(dtm: int) -> str:
    """The move count as a stipulation writes it: `13`, or `8.5`."""
    return str(dtm // 2) if dtm % 2 == 0 else f"{dtm // 2}.5"


def squares(fen: str):
    """Yield (rank_index_from_top, file_index, piece_char) for every man."""
    for r, rank in enumerate(fen.split()[0].split("/")):
        f = 0
        for ch in rank:
            if ch.isdigit():
                f += int(ch)
            else:
                yield r, f, ch
                f += 1


def piece_counts(fen: str) -> tuple[int, int]:
    """(white men, black men) -- the `2 + 3` under a diagram."""
    men = [p for _, _, p in squares(fen)]
    return sum(p.isupper() for p in men), sum(p.islower() for p in men)


def board(fen: str) -> str:
    """The board alone, in Popeye's ASCII diagram format.

    Black men carry a leading `-`, which is how Popeye distinguishes colour
    without relying on case -- it survives being read aloud, quoted in plain
    text, or pasted into a mail client that helpfully capitalises things.
    """
    grid = [[" ."] * 8 for _ in range(8)]
    for r, f, ch in squares(fen):
        letter = LETTER[ch.upper()]
        grid[r][f] = f" {letter}" if ch.isupper() else f"-{letter}"

    border = "+" + "".join(f"---{f}" for f in FILES) + "---+"
    inner = "|" + " " * (BOARD_WIDTH - 2) + "|"

    out = [border]
    for r in range(8):
        rank = 8 - r
        out.append(inner)
        out.append(f"{rank}" + "".join(f"  {c}" for c in grid[r]) + f"   {rank}")
    out.append(inner)
    out.append(border)
    return "\n".join(out)


def diagram(fen: str, dtm: int) -> str:
    """The board plus the caption line problemists expect under it.

    Stipulation on the left, material count on the right, aligned with the
    board's own right edge.
    """
    w, b = piece_counts(fen)
    left = f"  {hn(dtm)}"
    right = f"{w} + {b}"
    pad = BOARD_WIDTH - len(left) - len(right)
    return f"{board(fen)}\n{left}{' ' * pad}{right}"


def helpman_url(fen: str, dtm: int) -> str:
    """A Helpmate Analyzer deep link: helpman.komtera.lt.

    Only the board field goes in `fen`. Two reasons, both load-bearing:

    * the site parses its own query string in `transformToAssocArray()` by
      splitting on `&` and `=` -- there is no `decodeURIComponent` anywhere on
      that path, so a percent-encoded space arrives as a literal `%20` and the
      FEN fails to parse. The board field is `[A-Za-z0-9/]` only, which needs
      no encoding at all;
    * side to move is not carried by the FEN there. It is implied by the
      stipulation: `moves=13` is Black to play (the helpmate default),
      `moves=8.5` is White. That is exactly our dtm parity.
    """
    return (f"https://helpman.komtera.lt/?fen={fen.split()[0]}"
            f"&moves={moves_param(dtm)}")


def numbered(solution: str, dtm: int) -> str:
    """Helpmate notation, in which Black moves first.

    `1.Kb7 d5 2...` for a black-to-move problem; an odd depth is White to
    move, so it opens `1...` with White's move and Black's first reply starts
    move two.
    """
    moves = solution.split()
    if not moves:
        return ""
    out: list[str] = []
    if dtm % 2:                                  # White to move: 1...
        out.append(f"1...{moves[0]}")
        moves = moves[1:]
        n = 2
    else:
        n = 1
    for i in range(0, len(moves), 2):
        pair = " ".join(moves[i:i + 2])
        out.append(f"{n}.{pair}")
        n += 1
    return " ".join(out)


_TEX = {"\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$",
        "#": r"\#", "_": r"\_", "{": r"\{", "}": r"\}",
        "~": r"\textasciitilde{}", "^": r"\textasciicircum{}"}


def tex_escape(text: str) -> str:
    """Escape a literal string for LaTeX. `h#13` is the case that matters."""
    return "".join(_TEX.get(c, c) for c in text)
