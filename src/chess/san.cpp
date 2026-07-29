#include "chess/san.h"

namespace hm {

namespace {
char promo_letter(PieceType t) {
    switch (t) {
        case PieceType::Queen: return 'Q';
        case PieceType::Rook: return 'R';
        case PieceType::Bishop: return 'B';
        case PieceType::Knight: return 'N';
        default: return '?';
    }
}
}  // namespace

std::string san(Board& b, const Move& m) {
    auto pieces = b.pieces();

    PieceType moved = PieceType::Pawn;
    for (auto& pp : pieces)
        if (pp.square == m.from) { moved = pp.piece.type; break; }

    std::string s;
    bool is_pawn = (moved == PieceType::Pawn);

    if (!is_pawn) {
        static const char letters[5] = {'K', 'Q', 'R', 'B', 'N'};
        s += letters[(int)moved];

        // Disambiguation: scan other legal moves of the same piece type to the same target.
        auto moves = b.legal_moves();
        bool other_exists = false, same_file = false, same_rank = false;
        for (auto& other : moves) {
            if (other.to != m.to || other.from == m.from) continue;
            PieceType other_type = PieceType::Pawn;
            for (auto& pp : pieces)
                if (pp.square == other.from) { other_type = pp.piece.type; break; }
            if (other_type != moved) continue;
            other_exists = true;
            if (sq_file(other.from) == sq_file(m.from)) same_file = true;
            if (sq_rank(other.from) == sq_rank(m.from)) same_rank = true;
        }
        if (other_exists) {
            if (!same_file) s += char('a' + sq_file(m.from));
            else if (!same_rank) s += char('1' + sq_rank(m.from));
            else s += sq_name(m.from);
        }
    } else if (m.is_capture()) {
        s += char('a' + sq_file(m.from));
    }

    if (m.is_capture()) s += 'x';
    s += sq_name(m.to);

    if (auto pr = m.promotion()) {
        s += '=';
        s += promo_letter(*pr);
    }

    b.make(m);
    PosState st = b.state();
    if (st == PosState::Checkmate) s += '#';
    else if (st == PosState::Check) s += '+';
    b.unmake(m);

    return s;
}

}  // namespace hm
