#include <catch2/catch_test_macros.hpp>

#include "themes/position_themes.h"
#include "themes/registry.h"

using namespace hm;
using namespace hm::themes;

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

TEST_CASE("set-play: the DTM_MAX boundary itself", "[themes][position]") {
    // DTM_MAX (252) is the largest dtm a solved position can carry -- still a
    // "yes". DTM_UNSET (253) is one past it: not a real dtm at all, and must
    // read as "no" exactly like the two other reserved sentinels above.
    CHECK(setplay(ValuePair{DTM_MAX, 1}));
    CHECK_FALSE(setplay(ValuePair{DTM_UNSET, 0}));
}

TEST_CASE("set-play is registered and needs the plane", "[themes][registry]") {
    const auto* t = find_theme("set-play");
    REQUIRE(t != nullptr);
    REQUIRE(t->needs == Needs::Plane);
}
