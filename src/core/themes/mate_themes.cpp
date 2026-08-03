#include "themes/mate_themes.h"

#include "themes/attack.h"

namespace hm::themes {
namespace {

struct MateInfo {
    bool valid = false;  // false when there is no black king on the board
    int bk = -1;
    std::vector<PlacedPiece> pieces;
    std::vector<int> field;
};

MateInfo mate_info(const Solution& s) {
    MateInfo mi;
    mi.pieces = final_board(s).pieces();
    for (const auto& p : mi.pieces)
        if (p.piece.type == PieceType::King && p.piece.color == Color::Black) mi.bk = p.square;
    if (mi.bk < 0) return mi;
    mi.field = king_field(mi.bk);
    mi.valid = true;
    return mi;
}

const PlacedPiece* at_square(const std::vector<PlacedPiece>& ps, int sq) {
    for (const auto& p : ps)
        if ((int)p.square == sq) return &p;
    return nullptr;
}

bool on_field(const MateInfo& mi, int sq) {
    for (int f : mi.field)
        if (f == sq) return true;
    return false;
}

// A unit participates in the mate if it bears on the king's square or on any
// square of the king's field, or if it blocks a field square by standing on it.
bool participates(const MateInfo& mi, const PlacedPiece& p) {
    if (piece_attacks(mi.pieces, p, mi.bk)) return true;
    if (on_field(mi, p.square)) return true;
    for (int f : mi.field)
        if (piece_attacks(mi.pieces, p, f, Color::Black)) return true;
    return false;
}

}  // namespace

bool is_pure(const Solution& s) {
    MateInfo mi = mate_info(s);
    if (!mi.valid) return false;
    // The king's own square is judged on the FULL board: exactly one checker,
    // so double check is impure.
    if (attackers_of(mi.pieces, Color::White, mi.bk) != 1) return false;
    for (int f : mi.field) {
        // Field squares are judged with the mated king REMOVED, so a checking
        // slider also denies the square directly behind the king.
        const int a = attackers_of(mi.pieces, Color::White, f, Color::Black);
        const PlacedPiece* occ = at_square(mi.pieces, f);
        if (!occ) {
            if (a != 1) return false;  // unguarded, or guarded twice
        } else if (occ->piece.color == Color::Black) {
            if (a != 0) return false;  // self-block AND attacked: double duty
        }
        // Occupied by a white unit: the body blocks the square. Whether it is
        // also attacked is immaterial, by convention.
    }
    return true;
}

bool is_model(const Solution& s) {
    if (!is_pure(s)) return false;
    MateInfo mi = mate_info(s);
    for (const auto& p : mi.pieces) {
        if (p.piece.color != Color::White) continue;
        if (p.piece.type == PieceType::King || p.piece.type == PieceType::Pawn) continue;
        if (!participates(mi, p)) return false;
    }
    return true;
}

bool is_ideal(const Solution& s) {
    if (!is_model(s)) return false;
    MateInfo mi = mate_info(s);
    for (const auto& p : mi.pieces) {
        if (p.piece.color == Color::White) {
            if (!participates(mi, p)) return false;  // no exemptions here
        } else {
            if ((int)p.square == mi.bk) continue;       // the mated king participates by definition
            if (!on_field(mi, p.square)) return false;  // a black unit off the field does nothing
        }
    }
    return true;
}

bool is_mirror(const Solution& s) {
    MateInfo mi = mate_info(s);
    if (!mi.valid) return false;
    for (int f : mi.field)
        if (at_square(mi.pieces, f)) return false;
    return true;
}

}  // namespace hm::themes
