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
    # count[pos] mirrors the engine's own optimal-line accumulation
    # (src/generator/eval.h: count = sum of count[succ] over every successor
    # that achieves the best/minimal dtm, saturating at 255 == COUNT_SAT --
    # src/chess/types.h) but computed here purely in python-chess, summing
    # over ALL successors at dtm[succ] == d - 1 rather than stopping at the
    # first one (that's what turns this from a plain reachability BFS into a
    # count of distinct optimal cooperative lines).
    COUNT_SAT = 255
    dtm = {}
    count = {}
    fens = list(positions())
    boards = {f: chess.Board(f) for f in fens}
    def key(b):
        return b.epd()
    for f, b in boards.items():
        if b.turn == chess.BLACK and b.is_checkmate():
            k = key(b)
            dtm[k] = 0
            count[k] = 1
    d = 0
    changed = True
    while changed:
        d += 1; changed = False
        mover = chess.WHITE if d % 2 else chess.BLACK
        for f, b in boards.items():
            k = key(b)
            if k in dtm or b.turn != mover: continue
            total = 0
            for m in b.legal_moves:
                b.push(m); succ = key(b); b.pop()
                # A successor leaving the KQvk slice (Black captures the
                # queen -> Kvk) is never in `dtm`/`count`, so the lookup
                # below just misses and that move is silently excluded from
                # the tally -- correct here because Kvk is unconditionally
                # unsolvable. This "cross-slice successors are safe to skip"
                # argument is KQvk-specific (relies on the reduced material
                # being unconditionally unsolvable) and does not generalize
                # to materials whose reduced slices can themselves be mated.
                if succ in dtm and dtm[succ] == d - 1:
                    total += count[succ]
            if total > 0:
                dtm[k] = d
                count[k] = min(total, COUNT_SAT)
                changed = True
    for f in fens:
        p = tb.probe(f)
        k = key(boards[f])
        if p is None:
            assert dtm.get(k) is None, f
            continue
        assert p[0] == dtm.get(k), f
        # our engine's stored count saturates at COUNT_SAT (src/chess/types.h);
        # `count` above is capped identically, so this is a plain equality --
        # including in the (unreached for KQvk, but handled correctly) case
        # where both sides hit the same 255 cap.
        assert p[1] == count.get(k), f
