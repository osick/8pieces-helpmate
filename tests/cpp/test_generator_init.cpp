#include <catch2/catch_test_macros.hpp>
#include "generator/generator.h"
#include "chess/board.h"
using namespace hm;
static uint64_t cell_of(SliceGen& g, const std::string& fen) {
    auto b = Board::from_fen(fen); REQUIRE(b);
    auto e = g.index().encode(b->pieces()); REQUIRE(e); return *e;
}
TEST_CASE("init pass classifies KQvk") {
    SliceGen g(*Material::parse("KQvk"), {});
    g.init_pass();
    // G0 mate cell is dtm 0 on the btm plane
    uint64_t mate = cell_of(g, "7k/6Q1/5K2/8/8/8/8/8 b - - 0 1");
    CHECK(g.dtm(Color::Black)[mate] == 0);
    // same placement, wtm: Black in check but White to move -> INVALID
    CHECK(g.dtm(Color::White)[mate] == DTM_INVALID);
    // an open position is UNSET on both planes
    uint64_t open = cell_of(g, "8/7k/5K2/8/8/8/8/Q7 w - - 0 1");
    CHECK(g.dtm(Color::White)[open] == DTM_UNSET);
    CHECK(g.dtm(Color::Black)[open] == DTM_UNSET);
    // global invariants
    uint64_t mates = 0, invalid_w = 0;
    for (uint64_t c = 0; c < g.index().size(); ++c) {
        if (g.dtm(Color::Black)[c] == 0) mates++;
        if (g.dtm(Color::White)[c] == DTM_INVALID) invalid_w++;
        CHECK(g.dtm(Color::White)[c] != 0);            // wtm can never be dtm 0
    }
    CHECK(mates > 0); CHECK(invalid_w > 0);
}
TEST_CASE("init pass on Kvk finds no mates") {
    SliceGen g(*Material::parse("Kvk"), {});
    g.init_pass();
    for (uint64_t c = 0; c < g.index().size(); ++c)
        CHECK(g.dtm(Color::Black)[c] != 0);
}
