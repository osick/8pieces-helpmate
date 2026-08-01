#include <catch2/catch_test_macros.hpp>
#include "generator/oracle.h"
using namespace hm;
static OracleResult solve(const std::string& fen, int maxp = 12) {
    auto b = Board::from_fen(fen); REQUIRE(b);
    auto r = oracle_solve(*b, maxp); REQUIRE(r); return *r;
}
// G0: k h8, Q g7 (guarded by K f6) — Black already checkmated.
TEST_CASE("golden dtm 0") {
    auto r = solve("7k/6Q1/5K2/8/8/8/8/8 b - - 0 1");
    CHECK(r.dtm == 0); CHECK(r.count == 1);
}
// G1: same but Q on g1, wtm — 1. Qg7# is the only mate.
TEST_CASE("golden dtm 1, unique") {
    auto r = solve("7k/8/5K2/8/8/8/8/6Q1 w - - 0 1");
    CHECK(r.dtm == 1); CHECK(r.count == 1);
}
// G2: bK h7 — g6/g7/g8 illegal (g6/g7 adjacent to wK f6; g8 swept by Qg1 on
// the open g-file), leaving Kh8 and Kh6 as Black's only legal replies.
// 1...Kh8 2.Qg7# is one optimal line; 1...Kh6 opens the h-file, and with
// g5/g6/g7 covered by wK f6 and h5/h7 covered in each case, White has three
// more immediate mates: 2.Qg6#, 2.Qh1#, 2.Qh2#. Four distinct optimal lines
// total (hand-verified and confirmed via direct engine trace; the plan's
// original "Kh6 leads deeper" parenthetical was mistaken).
TEST_CASE("golden dtm 2, four optimal lines") {
    auto r = solve("8/7k/5K2/8/8/8/8/6Q1 b - - 0 1");
    CHECK(r.dtm == 2); CHECK(r.count == 4);
}
// G3: Q a1, wtm — 1. Qg1 Kh8 2. Qg7#. No mate in 1 (Qa1-g7 is blocked by wK f6).
TEST_CASE("golden dtm 3") {
    CHECK(solve("8/7k/5K2/8/8/8/8/Q7 w - - 0 1").dtm == 3);
}
// G4 promotion: wK g6, wP e7, bK g8, wtm — 1. e8=Q# and 1. e8=R# both mate: count 2.
TEST_CASE("golden promotion mate, count 2 (Q and R promotion)") {
    auto r = solve("6k1/4P3/6K1/8/8/8/8/8 w - - 0 1");
    CHECK(r.dtm == 1); CHECK(r.count == 2);
}
TEST_CASE("unsolvable within horizon") {
    auto b = Board::from_fen("8/8/8/8/8/4k3/8/4K3 w - - 0 1");   // Kvk
    CHECK(!oracle_solve(*b, 10));
}
TEST_CASE("stalemate has no continuation") {
    auto b = Board::from_fen("8/8/8/8/8/1Q6/2K5/k7 b - - 0 1");
    CHECK(!oracle_solve(*b, 8));
}
