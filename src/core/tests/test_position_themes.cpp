#include <catch2/catch_test_macros.hpp>

#include "themes/position_themes.h"
#include "themes/registry.h"

using namespace hm;
using namespace hm::themes;

static bool homebase(const std::string& fen) {
    auto b = Board::from_fen(fen);
    REQUIRE(b);
    std::vector<Solution> none;
    ThemeInput in{*b, std::nullopt, none};
    return is_homebase(in);
}

TEST_CASE("homebase: bare kings on their own squares", "[themes][position]") {
    CHECK(homebase("4k3/8/8/8/8/8/8/4K3 b - - 0 1"));
}

TEST_CASE("homebase: a king off its square breaks it", "[themes][position]") {
    CHECK_FALSE(homebase("4k3/8/8/8/8/8/8/3K4 b - - 0 1"));
}

TEST_CASE("homebase: officers on their game-array squares", "[themes][position]") {
    CHECK(homebase("4k3/8/8/8/8/8/8/R3K2R b - - 0 1"));
    CHECK(homebase("1n2k3/8/8/8/8/8/8/2B1K3 b - - 0 1"));
}

TEST_CASE("homebase: a pawn anywhere on its home rank counts", "[themes][position]") {
    // Deliberate spec decision: requiring the pawn's OWN file would make the
    // theme useless. A white pawn on d2 and a black pawn on f7 are both home,
    // even though neither stands on a d- or f-pawn's game-array file only by
    // coincidence -- rank is the whole test.
    CHECK(homebase("4k3/8/8/8/8/8/3P4/4K3 b - - 0 1"));
    CHECK(homebase("4k3/5p2/8/8/8/8/8/4K3 b - - 0 1"));
}

TEST_CASE("homebase: a black pawn on rank 7 counts, on rank 6 does not", "[themes][position]") {
    CHECK(homebase("4k3/3p4/8/8/8/8/8/4K3 b - - 0 1"));
    CHECK_FALSE(homebase("4k3/8/3p4/8/8/8/8/4K3 b - - 0 1"));
}

TEST_CASE("homebase: a queen on the wrong file breaks it", "[themes][position]") {
    CHECK(homebase("3qk3/8/8/8/8/8/8/3QK3 b - - 0 1"));
    CHECK_FALSE(homebase("4k3/8/8/8/8/8/8/4KQ2 b - - 0 1"));
}

TEST_CASE("homebase: a queen on the other colour's home square breaks it", "[themes][position]") {
    // Right file, wrong back rank: distinct from the wrong-file case above.
    CHECK_FALSE(homebase("3Qk3/8/8/8/8/8/8/4K3 b - - 0 1"));
}

TEST_CASE("homebase is registered and needs only the position", "[themes][registry]") {
    const auto* t = find_theme("homebase");
    REQUIRE(t != nullptr);
    REQUIRE(t->needs == Needs::Position);
}

static bool setplay(std::optional<ValuePair> other) {
    auto b = Board::from_fen("4k3/8/8/8/8/8/8/4K3 b - - 0 1");
    REQUIRE(b);
    std::vector<Solution> none;
    ThemeInput in{*b, other, none};
    return has_set_play(in);
}

TEST_CASE("set-play: the other plane being solvable is the whole definition", "[themes][position]") {
    CHECK(setplay(ValuePair{4, 1}));
    CHECK(setplay(ValuePair{0, 1}));
    CHECK_FALSE(setplay(ValuePair{DTM_UNSOLVABLE, 0}));
    CHECK_FALSE(setplay(ValuePair{DTM_INVALID, 0}));
    // Absent means "the caller did not fetch it" -- never guess a yes.
    CHECK_FALSE(setplay(std::nullopt));
}

TEST_CASE("set-play is registered and needs the plane", "[themes][registry]") {
    const auto* t = find_theme("set-play");
    REQUIRE(t != nullptr);
    REQUIRE(t->needs == Needs::Plane);
}
