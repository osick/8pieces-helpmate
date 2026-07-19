#include "indexing/kk.h"
#include "chess/types.h"
#include <set>
#include <climits>

namespace hm {

bool kings_adjacent(int a, int b) {
    int file_delta = abs(sq_file(a) - sq_file(b));
    int rank_delta = abs(sq_rank(a) - sq_rank(b));
    return file_delta <= 1 && rank_delta <= 1;
}

static KKTable build(bool pawns) {
    KKTable t;
    t.index_of.fill(-1);

    int max_transform = pawns ? 2 : 8;

    // Track which canonical pairs we've already added
    std::set<std::pair<int, int>> added;

    // Iterate all possible (wk, bk) pairs
    for (int wk = 0; wk < 64; ++wk) {
        for (int bk = 0; bk < 64; ++bk) {
            if (wk == bk || kings_adjacent(wk, bk)) continue;

            // Find canonical representative by applying transforms
            int best_wk = -1, best_bk = -1;
            int best_index = INT_MAX;

            for (int trans = 0; trans < max_transform; ++trans) {
                int wk_t = transform_sq(wk, trans);
                int bk_t = transform_sq(bk, trans);

                // Check if wK is in canonical region
                bool in_region = pawns ? sq_file(wk_t) < 4
                                       : (sq_file(wk_t) < 4 && sq_rank(wk_t) <= sq_file(wk_t));
                if (!in_region) continue;

                // Pick the lexicographically smallest canonical form
                int idx = wk_t * 64 + bk_t;
                if (idx < best_index) {
                    best_index = idx;
                    best_wk = wk_t;
                    best_bk = bk_t;
                }
            }

            // If we found a canonical representative, add it (but only once)
            if (best_wk != -1) {
                std::pair<int, int> key = {best_wk, best_bk};
                if (added.find(key) == added.end()) {
                    added.insert(key);
                    t.index_of[best_wk * 64 + best_bk] = t.size++;
                    t.squares_of.push_back({(uint8_t)best_wk, (uint8_t)best_bk});
                }
            }
        }
    }
    return t;
}

const KKTable& KKTable::with_pawns() {
    static const KKTable t = build(true);
    return t;
}

const KKTable& KKTable::pawnless() {
    static const KKTable t = build(false);
    return t;
}

}
