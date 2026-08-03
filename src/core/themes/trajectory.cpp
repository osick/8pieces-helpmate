#include "themes/trajectory.h"

#include <array>

namespace hm::themes {

std::vector<Trajectory> trajectories(const Solution& s) {
    std::vector<Trajectory> out;
    // where[colour][square] -> index into `out`, or -1 for "no tracked unit".
    std::array<std::array<int, 64>, 2> where;
    where[0].fill(-1);
    where[1].fill(-1);

    for (int i = 0; i < (int)s.plies.size(); ++i) {
        const Ply& p = s.plies[i];
        const int c = (int)p.piece.color;
        int t = where[c][p.from];
        if (t < 0) {
            out.push_back(Trajectory{p.piece.color, {p.from}, {}, false});
            t = (int)out.size() - 1;
        }
        where[c][p.from] = -1;

        // A captured unit stops existing; drop its entry so a later unit of
        // that colour arriving on the square cannot inherit its trajectory.
        // This cannot change a verdict as the loop stands -- a unit can only
        // reach the vacated square by MOVING there, and that arrival overwrites
        // the slot below anyway -- but it keeps `where` a truthful occupancy
        // map rather than leaving the invariant resting on that coincidence.
        // An en-passant victim stands beside the capture square, not on it.
        if (p.captured) {
            const int gone = p.is_ep ? (sq_rank(p.from) * 8 + sq_file(p.to)) : (int)p.to;
            where[1 - c][gone] = -1;
        }

        out[t].squares.push_back(p.to);
        out[t].plies.push_back(i);
        if (p.promotion) out[t].promoted = true;
        where[c][p.to] = t;
    }
    return out;
}

}  // namespace hm::themes
