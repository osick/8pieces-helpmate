#include "themes/position_themes.h"

namespace hm::themes {

namespace {
// Home squares by piece type for White; Black's are the same files on rank 8.
bool on_home_square(Piece p, int sq) {
    const int file = sq_file(sq), rank = sq_rank(sq);
    const int back = p.color == Color::White ? 0 : 7;
    const int pawn_rank = p.color == Color::White ? 1 : 6;
    switch (p.type) {
        case PieceType::Pawn:
            return rank == pawn_rank;
        case PieceType::King:
            return rank == back && file == 4;
        case PieceType::Queen:
            return rank == back && file == 3;
        case PieceType::Rook:
            return rank == back && (file == 0 || file == 7);
        case PieceType::Bishop:
            return rank == back && (file == 2 || file == 5);
        case PieceType::Knight:
            return rank == back && (file == 1 || file == 6);
    }
    return false;
}
}  // namespace

bool is_homebase(const ThemeInput& in) {
    for (const auto& pp : in.start.pieces())
        if (!on_home_square(pp.piece, pp.square)) return false;
    return true;
}

}  // namespace hm::themes
