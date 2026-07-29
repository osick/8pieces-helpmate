#pragma once
#include "chess/board.h"
#include "chess/types.h"
#include <climits>

namespace hm {

// LookupFn: ValuePair(Board&) — value of an EP-less position (board's material may
// differ from the caller's slice; the function routes to the right table).
// eval_board: value of the position in b including any EP rights b carries.
// If b has an EP square, every legal EP capture r contributes (1 + value(after r));
// the EP-less table value contributes as-is; result is the min, counts summed over
// branches achieving the min (saturating).
template <class LookupFn>
ValuePair eval_board(Board& b, LookupFn&& lookup) {
    int best = INT_MAX; unsigned count = 0;
    ValuePair base = lookup(b);
    if (base.dtm <= DTM_MAX) { best = base.dtm; count = base.count; }
    if (b.ep_square() >= 0) {
        for (const Move& r : b.legal_moves()) {
            if (!r.is_ep()) continue;
            b.make(r);
            ValuePair v = lookup(b);                  // EP capture never creates new EP rights
            b.unmake(r);
            if (v.dtm > DTM_MAX) continue;
            int via = v.dtm + 1;
            if (via < best) { best = via; count = v.count; }
            else if (via == best) count = std::min(255u, count + (unsigned)v.count);
        }
    }
    if (best == INT_MAX) return {DTM_UNSOLVABLE, 0};
    return {(uint8_t)best, (uint8_t)count};
}

}  // namespace hm
