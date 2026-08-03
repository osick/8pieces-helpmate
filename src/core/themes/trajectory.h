#pragma once
#include <vector>

#include "probe/solution.h"

namespace hm::themes {

// The path one unit takes through a solution: the squares it occupied in
// order, and the indices of the plies that moved it.
struct Trajectory {
    Color color = Color::White;
    std::vector<uint8_t> squares;  // origin first, final square last
    std::vector<int> plies;        // size == squares.size() - 1
    bool promoted = false;         // one of its plies promoted
};

// One entry per unit that moved at least once, in order of first movement.
// Units are chained by square: a ply moving from a square a tracked unit
// currently occupies continues that unit's trajectory.
std::vector<Trajectory> trajectories(const Solution& s);

}  // namespace hm::themes
