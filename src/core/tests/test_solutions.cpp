#include "probe/tablebase.h"
#include "probe/solution.h"
#include "generator/generator.h"
#include <catch2/catch_test_macros.hpp>
#include <filesystem>
#include <set>

using namespace hm;

// The golden KQvk position: dtm 2, count 4, four known optimal solutions.
// Already pinned by tests across the C++, Python and CLI suites.
static const char* kGolden = "8/7k/5K2/8/8/8/8/6Q1 b - - 0 1";

namespace {
std::string gen_kqvk() {
    static std::string dir;
    if (dir.empty()) {
        dir = (std::filesystem::temp_directory_path() / "hm_solutions_test").string();
        std::filesystem::create_directories(dir);
        GenOptions opt; opt.tables_dir = dir;
        generate(*Material::parse("KQvk"), opt);
    }
    return dir;
}
}  // namespace

TEST_CASE("solutions() mirrors lines() one-for-one", "[themes][solutions]") {
    Tablebase tb(gen_kqvk());
    auto ls = tb.lines(kGolden, 100);
    auto ss = tb.solutions(kGolden, 100);
    REQUIRE(ss.size() == ls.size());
    REQUIRE(ss.size() == 4);
    for (size_t i = 0; i < ss.size(); ++i) REQUIRE(ss[i].plies.size() == ls[i].size());
}

TEST_CASE("every solution carries the queried position as start", "[themes][solutions]") {
    Tablebase tb(gen_kqvk());
    for (const auto& s : tb.solutions(kGolden, 100)) REQUIRE(s.start.fen() == kGolden);
}

TEST_CASE("the last ply of every optimal solution is mate", "[themes][solutions]") {
    Tablebase tb(gen_kqvk());
    for (const auto& s : tb.solutions(kGolden, 100)) {
        REQUIRE(!s.plies.empty());
        REQUIRE(s.plies.back().is_check);
        REQUIRE(final_board(s).state() == PosState::Checkmate);
    }
}

TEST_CASE("plies record the moving unit and its from/to", "[themes][solutions]") {
    Tablebase tb(gen_kqvk());
    auto ss = tb.solutions(kGolden, 100);
    for (const auto& s : ss) {
        // h#1: Black moves first, then White mates.
        REQUIRE(s.plies.size() == 2);
        REQUIRE(s.plies[0].piece.color == Color::Black);
        REQUIRE(s.plies[0].piece.type == PieceType::King);
        REQUIRE(s.plies[1].piece.color == Color::White);
        for (const auto& p : s.plies) {
            REQUIRE(p.from != p.to);
            REQUIRE_FALSE(p.captured.has_value());   // no captures in this material
            REQUIRE_FALSE(p.promotion.has_value());
            REQUIRE_FALSE(p.is_ep);
        }
    }
}

TEST_CASE("a position that is already mate yields one empty solution", "[themes][solutions]") {
    Tablebase tb(gen_kqvk());
    const char* mated = "8/8/8/8/8/8/8/kQK5 b - - 0 1";   // dtm 0
    auto ss = tb.solutions(mated, 100);
    REQUIRE(ss.size() == 1);
    REQUIRE(ss[0].plies.empty());
    REQUIRE(final_board(ss[0]).fen() == mated);           // start is the mate
}

TEST_CASE("solutions() rejects a bad FEN the same way lines() does",
          "[themes][solutions]") {
    Tablebase tb(gen_kqvk());
    REQUIRE_THROWS_AS(tb.solutions("garbage", 10), std::invalid_argument);
}
