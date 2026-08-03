#include "themes/attack.h"
#include <array>
#include <cstdlib>
#include <utility>

namespace hm::themes {
namespace {

constexpr std::array<std::pair<int, int>, 8> kKingDirs{
    {{1, 0}, {-1, 0}, {0, 1}, {0, -1}, {1, 1}, {1, -1}, {-1, 1}, {-1, -1}}};
constexpr std::array<std::pair<int, int>, 8> kKnightDirs{
    {{1, 2}, {2, 1}, {2, -1}, {1, -2}, {-1, -2}, {-2, -1}, {-2, 1}, {-1, 2}}};

inline bool on_board(int f, int r) { return f >= 0 && f < 8 && r >= 0 && r < 8; }
inline int sq_of(int f, int r) { return r * 8 + f; }

// True when this unit is invisible for the current query.
inline bool hidden(const PlacedPiece& p, std::optional<Color> ignore_king_of) {
    return ignore_king_of && p.piece.type == PieceType::King && p.piece.color == *ignore_king_of;
}

}  // namespace

std::vector<int> king_field(int sq) {
    std::vector<int> out;
    int f = sq_file(sq), r = sq_rank(sq);
    for (auto [df, dr] : kKingDirs)
        if (on_board(f + df, r + dr)) out.push_back(sq_of(f + df, r + dr));
    return out;
}

int attackers_of(const std::vector<PlacedPiece>& pieces, Color by, int sq,
                 std::optional<Color> ignore_king_of) {
    std::array<int, 64> occ;
    occ.fill(-1);
    for (size_t i = 0; i < pieces.size(); ++i)
        if (!hidden(pieces[i], ignore_king_of)) occ[pieces[i].square] = (int)i;

    int n = 0;
    const int f = sq_file(sq), r = sq_rank(sq);

    auto steps = [&](const auto& dirs, PieceType want) {
        for (auto [df, dr] : dirs) {
            if (!on_board(f + df, r + dr)) continue;
            int i = occ[sq_of(f + df, r + dr)];
            if (i >= 0 && pieces[i].piece.color == by && pieces[i].piece.type == want) ++n;
        }
    };
    steps(kKnightDirs, PieceType::Knight);
    steps(kKingDirs, PieceType::King);

    // A pawn of colour `by` attacks `sq` from one rank BEHIND it in that
    // colour's direction of travel -- diagonally only, never the push square.
    const int pr = r - (by == Color::White ? 1 : -1);
    for (int df : {-1, 1}) {
        if (!on_board(f + df, pr)) continue;
        int i = occ[sq_of(f + df, pr)];
        if (i >= 0 && pieces[i].piece.color == by && pieces[i].piece.type == PieceType::Pawn) ++n;
    }

    // Sliders: walk each ray outward and stop at the first occupied square.
    for (auto [df, dr] : kKingDirs) {
        const bool diagonal = (df != 0 && dr != 0);
        for (int step = 1;; ++step) {
            int nf = f + df * step, nr = r + dr * step;
            if (!on_board(nf, nr)) break;
            int i = occ[sq_of(nf, nr)];
            if (i < 0) continue;
            const Piece& pc = pieces[i].piece;
            if (pc.color == by &&
                (pc.type == PieceType::Queen ||
                 pc.type == (diagonal ? PieceType::Bishop : PieceType::Rook)))
                ++n;
            break;  // the ray is blocked either way
        }
    }
    return n;
}

bool piece_attacks(const std::vector<PlacedPiece>& pieces, const PlacedPiece& p, int sq,
                   std::optional<Color> ignore_king_of) {
    if ((int)p.square == sq) return false;
    const int pf = sq_file(p.square), pr = sq_rank(p.square);
    const int tf = sq_file(sq), tr = sq_rank(sq);
    const int df = tf - pf, dr = tr - pr;

    switch (p.piece.type) {
        case PieceType::Knight:
            return (std::abs(df) == 1 && std::abs(dr) == 2) ||
                   (std::abs(df) == 2 && std::abs(dr) == 1);
        case PieceType::King:
            return std::abs(df) <= 1 && std::abs(dr) <= 1;
        case PieceType::Pawn:
            return std::abs(df) == 1 && dr == (p.piece.color == Color::White ? 1 : -1);
        default:
            break;
    }
    const bool diagonal = (std::abs(df) == std::abs(dr));
    const bool straight = (df == 0 || dr == 0);
    if (p.piece.type == PieceType::Bishop && !diagonal) return false;
    if (p.piece.type == PieceType::Rook && !straight) return false;
    if (p.piece.type == PieceType::Queen && !diagonal && !straight) return false;

    const int sf = (df > 0) - (df < 0), sr = (dr > 0) - (dr < 0);
    for (int f = pf + sf, r = pr + sr; f != tf || r != tr; f += sf, r += sr) {
        const int between = sq_of(f, r);
        for (const auto& o : pieces)
            if (!hidden(o, ignore_king_of) && (int)o.square == between) return false;
    }
    return true;
}

}  // namespace hm::themes
