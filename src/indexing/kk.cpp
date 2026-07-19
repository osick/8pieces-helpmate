#include "indexing/kk.h"
#include "chess/types.h"
#include <cstdlib>

namespace hm {

bool kings_adjacent(int a, int b) {
    int file_delta = std::abs(sq_file(a) - sq_file(b));
    int rank_delta = std::abs(sq_rank(a) - sq_rank(b));
    return file_delta <= 1 && rank_delta <= 1;
}

static KKTable build(bool pawns) {
    KKTable t;
    t.index_of.fill(-1);
    for (int wk = 0; wk < 64; ++wk) {
        bool ok = pawns ? sq_file(wk) < 4
                        : (sq_file(wk) < 4 && sq_rank(wk) <= sq_file(wk));
        if (!ok) continue;
        // Pawnless: when wK is on the a1-h8 diagonal, positions with bK above the
        // diagonal are transpose-images of ones below it; restrict bK to rank<=file
        // to keep exactly one representative (564 -> 462).
        bool wk_on_diag = !pawns && sq_rank(wk) == sq_file(wk);
        for (int bk = 0; bk < 64; ++bk) {
            if (bk == wk || kings_adjacent(wk, bk)) continue;
            if (wk_on_diag && sq_rank(bk) > sq_file(bk)) continue;
            t.index_of[wk * 64 + bk] = t.size++;
            t.squares_of.push_back({(uint8_t)wk, (uint8_t)bk});
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
