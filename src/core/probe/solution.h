#pragma once
#include <optional>
#include <vector>

#include "chess/board.h"
#include "chess/types.h"

namespace hm {

// One ply of an optimal solution, carrying everything a theme detector needs.
// SAN is deliberately absent: `Tablebase::lines()` stays the cheaper path for
// callers that only want text, and nothing here needs a move rendered.
struct Ply {
    Piece piece;  // what moved; `type` is the type BEFORE any promotion
    uint8_t from = 0, to = 0;
    std::optional<PieceType> captured;   // nullopt if the ply is quiet
    std::optional<PieceType> promotion;  // nullopt if the ply is not a promotion
    bool is_ep = false;
    bool is_check = false;  // the side to move AFTER this ply is in check
    Board after;            // the position after this ply
};

// One optimal solution from a queried position.
//
// `start` is not redundant with `plies`. A position with dtm == 0 is already
// mate and carries no plies at all, and the mate-position detectors still need
// a board to read. `self-block` also needs the position immediately before a
// blocking move, which for the first ply is `start`.
struct Solution {
    Board start;
    std::vector<Ply> plies;
};

// The mating position: the board after the last ply, or `start` when the
// queried position was itself the mate.
inline const Board& final_board(const Solution& s) {
    return s.plies.empty() ? s.start : s.plies.back().after;
}

}  // namespace hm
