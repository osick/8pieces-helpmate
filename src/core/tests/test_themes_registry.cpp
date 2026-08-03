#include <algorithm>
#include <catch2/catch_test_macros.hpp>
#include <set>

#include "themes/registry.h"

using namespace hm;
using namespace hm::themes;

static Solution at(const std::string& fen) {
    auto b = Board::from_fen(fen);
    REQUIRE(b);
    return Solution{*b, {}};
}

TEST_CASE("the registry holds all sixteen entries", "[themes][registry]") {
    REQUIRE(theme_registry().size() == 16);
}

TEST_CASE("every entry has a name, a detector and a doc", "[themes][registry]") {
    for (const auto& t : theme_registry()) {
        REQUIRE_FALSE(t.name.empty());
        REQUIRE(t.fn != nullptr);
        REQUIRE_FALSE(t.doc.empty());
    }
}

TEST_CASE("names are unique", "[themes][registry]") {
    std::set<std::string_view> seen;
    for (const auto& t : theme_registry()) REQUIRE(seen.insert(t.name).second);
}

TEST_CASE("every documented theme is findable by name", "[themes][registry]") {
    for (const char* n : {"pure", "model", "ideal", "mirror", "promotion", "underpromotion", "excelsior",
                          "excelsior:white", "excelsior:black", "switchback", "closed-walk", "self-block",
                          "single-piece", "single-piece:white", "single-piece:black", "en-passant"})
        REQUIRE(find_theme(n) != nullptr);
}

TEST_CASE("an unknown name is not found", "[themes][registry]") {
    REQUIRE(find_theme("rundlauf") == nullptr);  // the English name is closed-walk
    REQUIRE(find_theme("") == nullptr);
    REQUIRE(find_theme("PURE") == nullptr);  // matching is exact, not case-folded
}

TEST_CASE("detect uses any semantics across solutions", "[themes][registry]") {
    // The back-rank model mate from test_mate_themes.cpp's kBase: black Kg8,
    // white Ra8 + Kg6. The brief's original FEN here (king on f7) is not even
    // checkmate -- h7 is an open, unattacked flight square -- so it was
    // replaced with the verified fixture; see task-5-report.md for the
    // discrepancy writeup.
    auto model_mate = at("R5k1/8/6K1/8/8/8/8/8 b - - 0 1");
    auto not_mate = at("8/8/8/8/8/8/8/K6k w - - 0 1");

    auto only_second = detect({not_mate, model_mate});
    REQUIRE(std::find(only_second.begin(), only_second.end(), "model") != only_second.end());

    auto neither = detect({not_mate});
    REQUIRE(std::find(neither.begin(), neither.end(), "model") == neither.end());
}

TEST_CASE("detect returns names in registry order", "[themes][registry]") {
    auto names = detect({at("R5k1/8/6K1/8/8/8/8/8 b - - 0 1")});
    size_t prev = 0;
    for (const auto& n : names) {
        size_t idx = 0;
        while (theme_registry()[idx].name != n) ++idx;
        REQUIRE(idx >= prev);
        prev = idx;
    }
}

TEST_CASE("detect on an empty solution set finds nothing", "[themes][registry]") {
    REQUIRE(detect({}).empty());
}
