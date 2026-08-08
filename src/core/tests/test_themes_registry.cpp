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

    std::vector<Solution> both{not_mate, model_mate};
    ThemeInput both_in{model_mate.start, std::nullopt, both};
    auto only_second = detect(both_in);
    REQUIRE(std::find(only_second.begin(), only_second.end(), "model") != only_second.end());

    std::vector<Solution> one{not_mate};
    ThemeInput one_in{not_mate.start, std::nullopt, one};
    auto neither = detect(one_in);
    REQUIRE(std::find(neither.begin(), neither.end(), "model") == neither.end());
}

TEST_CASE("detect returns names in registry order", "[themes][registry]") {
    auto mate = at("R5k1/8/6K1/8/8/8/8/8 b - - 0 1");
    std::vector<Solution> sols{mate};
    ThemeInput in{mate.start, std::nullopt, sols};
    auto names = detect(in);
    size_t prev = 0;
    for (const auto& n : names) {
        size_t idx = 0;
        while (theme_registry()[idx].name != n) ++idx;
        REQUIRE(idx >= prev);
        prev = idx;
    }
}

TEST_CASE("detect on an empty solution set finds nothing", "[themes][registry]") {
    auto b = Board::from_fen("8/8/8/8/8/8/8/K6k w - - 0 1");
    REQUIRE(b);
    std::vector<Solution> sols;
    ThemeInput in{*b, std::nullopt, sols};
    REQUIRE(detect(in).empty());
}

TEST_CASE("every entry declares what input it needs", "[themes][registry]") {
    for (const auto& t : theme_registry()) REQUIRE(t.needs == Needs::Solutions);
}

TEST_CASE("any_of finds a theme shown by only ONE of several solutions", "[themes][registry]") {
    // This is the `any` path that any_of<> now owns, so the test must be able
    // to fail if any_of<> is broken. Solution 1 shows nothing; solution 2
    // really promotes -- built from a legal move the engine produced, never a
    // Ply typed by hand.
    auto b = Board::from_fen("8/P6k/8/8/8/8/8/K7 w - - 0 1");
    REQUIRE(b);
    const Move* promo = nullptr;
    auto legal = b->legal_moves();
    for (const auto& m : legal)
        if (m.promotion() == PieceType::Queen) promo = &m;
    REQUIRE(promo != nullptr);  // the fixture FEN really does allow a promotion

    Solution plain{*b, {}};
    Solution promoting{*b, {}};
    Ply p;
    p.piece = {Color::White, PieceType::Pawn};
    p.from = promo->from;
    p.to = promo->to;
    p.promotion = promo->promotion();
    Board after = *b;
    after.make(*promo);
    p.after = after;
    promoting.plies.push_back(p);

    std::vector<Solution> sols{plain, promoting};
    ThemeInput in{*b, std::nullopt, sols};
    auto names = detect(in);
    REQUIRE(std::find(names.begin(), names.end(), "promotion") != names.end());
}
