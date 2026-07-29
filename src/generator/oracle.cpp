#include "generator/oracle.h"
#include <unordered_map>

namespace hm {
namespace {

struct Ctx {
    std::unordered_map<uint64_t, int> memo;  // key: hash() * 1000003 + plies_left
};

// Number of move sequences of length EXACTLY plies_left that end in Black
// checkmated (saturating at 255). For the minimal target this equals the
// optimal-line count: any successor s of a dtm-d position has dtm(s) >= d-1,
// so exact-length lines can only pass through optimal successors.
int paths(Board& b, int plies_left, Ctx& c) {
    if (plies_left == 0)
        return (b.stm() == Color::Black && b.state() == PosState::Checkmate) ? 1 : 0;
    uint64_t key = b.hash() * 1000003ull + (uint64_t)plies_left;
    if (auto it = c.memo.find(key); it != c.memo.end()) return it->second;
    unsigned total = 0;
    for (const Move& m : b.legal_moves()) {
        b.make(m);
        total = sat_add(total, (unsigned)paths(b, plies_left - 1, c));
        b.unmake(m);
    }
    c.memo.emplace(key, (int)total);
    return (int)total;
}

}  // namespace

std::optional<OracleResult> oracle_solve(Board b, int max_plies) {
    Ctx c;
    int start = (b.stm() == Color::Black) ? 0 : 1;  // parity: btm even, wtm odd
    for (int target = start; target <= max_plies; target += 2) {
        int n = paths(b, target, c);
        if (n > 0) return OracleResult{target, n};
    }
    return std::nullopt;
}

}  // namespace hm
