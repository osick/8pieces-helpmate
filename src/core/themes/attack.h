#pragma once
#include "chess/types.h"
#include <optional>
#include <vector>

namespace hm::themes {

// How many units of colour `by` attack `sq`.
//
// A PINNED unit counts as attacking. It still controls the square for the
// purpose of the enemy king's legality, and "would this pin actually matter"
// is not decidable from the position alone.
//
// `ignore_king_of`, when set, removes that colour's king from the occupancy
// before tracing sliders. Every FIELD-SQUARE test needs this: a rook on h1
// checking a king on h5 also denies h6, but with the king on the board it
// blocks the ray and h6 reads as unattacked. Tests of the king's OWN square
// use the full board.
int attackers_of(const std::vector<PlacedPiece>& pieces, Color by, int sq,
                 std::optional<Color> ignore_king_of = std::nullopt);

// Does this one unit attack `sq`, given `pieces` as the occupancy? Same
// pinned-counts and ignore_king_of rules as attackers_of. Used to ask whether
// a particular unit participates in a mate.
bool piece_attacks(const std::vector<PlacedPiece>& pieces, const PlacedPiece& p, int sq,
                   std::optional<Color> ignore_king_of = std::nullopt);

// The on-board squares adjacent to `sq` -- 8 in the middle, 3 in a corner.
std::vector<int> king_field(int sq);

}  // namespace hm::themes
