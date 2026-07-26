import random, itertools, pytest, chess
from helpmate import _helpmate as core
import helpmate

PIECES = [chess.QUEEN, chess.ROOK, chess.BISHOP, chess.KNIGHT, chess.PAWN]


def random_position(rng, n_extra):
    """Random legal castling-free position with 2 kings + n_extra pieces."""
    while True:
        squares = rng.sample(range(64), 2 + n_extra)
        board = chess.Board(None)
        board.set_piece_at(squares[0], chess.Piece(chess.KING, chess.WHITE))
        board.set_piece_at(squares[1], chess.Piece(chess.KING, chess.BLACK))
        for sq in squares[2:]:
            pt = rng.choice(PIECES)
            if pt == chess.PAWN and not (8 <= sq < 56):
                break
            board.set_piece_at(sq, chess.Piece(pt, rng.choice([chess.WHITE, chess.BLACK])))
        else:
            board.turn = rng.choice([chess.WHITE, chess.BLACK])
            if board.is_valid():
                return board


def test_movegen_matches_python_chess():
    rng = random.Random(1234)
    for _ in range(200):
        board = random_position(rng, rng.randint(1, 5))
        fen = board.fen()
        ours = sorted(core._legal_moves(fen))
        ref = sorted(m.uci() for m in board.legal_moves)
        assert ours == ref, fen


def test_perft_matches_python_chess():
    def ref_perft(board, d):
        if d == 0: return 1
        return sum(ref_perft_after(board, m, d) for m in board.legal_moves)
    def ref_perft_after(board, m, d):
        board.push(m); n = ref_perft(board, d - 1); board.pop(); return n
    rng = random.Random(99)
    for _ in range(25):
        board = random_position(rng, rng.randint(1, 4))
        assert core._perft(board.fen(), 3) == ref_perft(board, 3), board.fen()


@pytest.mark.slow
def test_exhaustive_kqvk(tmp_path):
    """Full independent BFS of KQvk with python-chess vs every probe value."""
    tables = str(tmp_path / "t")
    helpmate.generate("KQvk", tables=tables)
    tb = helpmate.Tablebase(tables)
    # enumerate all placements: wK, bK, wQ on distinct squares, both stm
    def positions():
        for wk, bk, q in itertools.permutations(range(64), 3):
            if chess.square_distance(wk, bk) <= 1: continue
            b = chess.Board(None)
            b.set_piece_at(wk, chess.Piece(chess.KING, chess.WHITE))
            b.set_piece_at(bk, chess.Piece(chess.KING, chess.BLACK))
            b.set_piece_at(q, chess.Piece(chess.QUEEN, chess.WHITE))
            for turn in (chess.WHITE, chess.BLACK):
                b.turn = turn
                if b.is_valid(): yield b.fen()
    # forward-scan BFS in pure python-chess (independent of all our code)
    #
    # Keyed by board.epd() rather than board.fen(): fen() includes the
    # halfmove-clock/fullmove-number suffix, which increments on every push()
    # (no captures/pawn moves exist inside the KQvk closure to reset it), so a
    # successor's fen() would never equal any canonical fens()-generated key
    # (always "... 0 1") and the BFS would silently get stuck at depth 0,
    # reporting every solvable position as unsolvable (found via the very
    # first cross-check mismatch: dtm=8 on 8/8/8/8/8/8/8/KQk5 b, independently
    # confirmed legal+mating in python-chess itself). epd() drops those two
    # fields (no castling rights or en passant square ever arise in KQvk, so
    # it remains a collision-free position key).
    dtm = {}
    fens = list(positions())
    boards = {f: chess.Board(f) for f in fens}
    key = lambda b: b.epd()
    for f, b in boards.items():
        if b.turn == chess.BLACK and b.is_checkmate(): dtm[key(b)] = 0
    d = 0
    changed = True
    while changed:
        d += 1; changed = False
        mover = chess.WHITE if d % 2 else chess.BLACK
        for f, b in boards.items():
            k = key(b)
            if k in dtm or b.turn != mover: continue
            for m in b.legal_moves:
                b.push(m); succ = key(b); b.pop()
                # captures leave KQvk -> Kvk or KvK-with-Q-captured: all unsolvable, skip
                if succ in dtm and dtm[succ] == d - 1:
                    dtm[k] = d; changed = True; break
    for f in fens:
        p = tb.probe(f)
        assert (p[0] if p else None) == dtm.get(key(boards[f])), f
