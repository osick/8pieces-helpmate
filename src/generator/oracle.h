#pragma once
#include "chess/board.h"
#include <optional>

namespace hm {

struct OracleResult {
    int dtm;
    int count;  // number of distinct optimal lines, saturating at 255
};

// Smallest ply distance to "Black is checkmated" with both sides cooperating,
// searching real game rules via Board (incl. EP, promotions, captures).
// nullopt if no mate within max_plies.
// Depends only on Board (T2), so it can cross-check indexing/tables later.
std::optional<OracleResult> oracle_solve(Board b, int max_plies);

}  // namespace hm
