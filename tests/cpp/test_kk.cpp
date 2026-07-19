#include <catch2/catch_test_macros.hpp>
#include "indexing/kk.h"
#include "chess/types.h"
using namespace hm;
TEST_CASE("transform_sq basics and bijectivity") {
    CHECK(transform_sq(0, 0) == 0);
    CHECK(transform_sq(0, 1) == 7);      // a1 -> h1
    CHECK(transform_sq(0, 2) == 56);     // a1 -> a8
    CHECK(transform_sq(1, 4) == 8);      // b1 -> a2 (transpose)
    for (int t = 0; t < 8; ++t) {
        bool seen[64] = {};
        for (int s = 0; s < 64; ++s) { int x = transform_sq(s, t); REQUIRE(!seen[x]); seen[x] = true; }
    }
}
TEST_CASE("kk table sizes are the standard values") {
    CHECK(KKTable::with_pawns().size == 1806);
    CHECK(KKTable::pawnless().size == 462);
}
TEST_CASE("kk tables are consistent bijections") {
    for (auto* tbl : {&KKTable::with_pawns(), &KKTable::pawnless()}) {
        for (int i = 0; i < tbl->size; ++i) {
            auto [wk, bk] = tbl->squares_of[i];
            CHECK(tbl->index_of[wk * 64 + bk] == i);
            CHECK(!kings_adjacent(wk, bk)); CHECK(wk != bk);
        }
    }
}
TEST_CASE("every king square reaches the canonical region") {
    for (int wk = 0; wk < 64; ++wk) {                 // pawns: exactly one of {id, mirror}
        int hits = 0;
        for (int t = 0; t < 2; ++t) if (sq_file(transform_sq(wk, t)) < 4) hits++;
        CHECK(hits == 1);
    }
    auto in_tri = [](int s) { return sq_file(s) < 4 && sq_rank(s) <= sq_file(s); };
    for (int wk = 0; wk < 64; ++wk) {                 // pawnless: at least one of 8
        int hits = 0;
        for (int t = 0; t < 8; ++t) if (in_tri(transform_sq(wk, t))) hits++;
        CHECK(hits >= 1);
    }
}
