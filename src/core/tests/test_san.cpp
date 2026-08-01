#include <catch2/catch_test_macros.hpp>
#include "chess/board.h"
#include "chess/san.h"
using namespace hm;
static std::string san_of(const std::string& fen, const std::string& uci) {
    auto b = Board::from_fen(fen); REQUIRE(b);
    for (auto& m : b->legal_moves()) if (m.uci() == uci) return san(*b, m);
    FAIL("move not legal"); return "";
}
TEST_CASE("san basics") {
    CHECK(san_of("7k/8/5K2/8/8/8/8/6Q1 w - - 0 1", "g1g7") == "Qg7#");
    CHECK(san_of("6k1/4P3/6K1/8/8/8/8/8 w - - 0 1", "e7e8q") == "e8=Q#");
    CHECK(san_of("6k1/4P3/6K1/8/8/8/8/8 w - - 0 1", "e7e8n") == "e8=N");
    CHECK(san_of("8/8/8/8/1p6/8/P7/K1k5 w - - 0 1", "a2a4") == "a4");
    // pawn capture with file prefix:
    CHECK(san_of("8/8/8/3p4/2P5/8/8/K1k5 w - - 0 1", "c4d5") == "cxd5");
    // disambiguation: two rooks on same rank, both reach d4
    CHECK(san_of("8/8/8/8/R6R/8/8/k3K3 w - - 0 1", "a4d4") == "Rad4");
}
