#include <catch2/catch_test_macros.hpp>

#include "themes/position_themes.h"
#include "themes/registry.h"

using namespace hm;
using namespace hm::themes;

static bool setplay(ValuePair value, std::optional<ValuePair> other) {
    auto b = Board::from_fen("4k3/8/8/8/8/8/8/4K3 b - - 0 1");
    REQUIRE(b);
    std::vector<Solution> none;
    ThemeInput in{*b, value, other, none};
    return has_set_play(in);
}

TEST_CASE("set-play: sibling at D - 1 is set play", "[themes][position]") {
    // The mate is already available one move sooner; the side to move
    // merely delays it. This is the D - 1 case from the bug report.
    CHECK(setplay(ValuePair{2, 1}, ValuePair{1, 1}));
    CHECK(setplay(ValuePair{4, 1}, ValuePair{3, 1}));
}

TEST_CASE("set-play: sibling at D + 1 is NOT set play -- the regression", "[themes][position]") {
    // This is the bug: flipping the side to move makes the mate LONGER, the
    // opposite of set play. The old detector ("other plane solvable, full
    // stop") reported this as a hit; it must not any more.
    CHECK_FALSE(setplay(ValuePair{2, 1}, ValuePair{3, 1}));
}

TEST_CASE("set-play: sibling much shorter than D - 1 is NOT set play", "[themes][position]") {
    // A sibling solvable well before D - 1 is the separate, unimplemented
    // "Short set play" notion (any shorter distance), not this theme.
    CHECK_FALSE(setplay(ValuePair{4, 1}, ValuePair{1, 1}));
}

TEST_CASE("set-play: sibling sentinels all read as no", "[themes][position]") {
    CHECK_FALSE(setplay(ValuePair{4, 1}, ValuePair{DTM_UNSOLVABLE, 0}));
    CHECK_FALSE(setplay(ValuePair{4, 1}, ValuePair{DTM_INVALID, 0}));
    CHECK_FALSE(setplay(ValuePair{4, 1}, ValuePair{DTM_UNSET, 0}));
    // Absent means "the caller did not fetch it" -- never guess a yes.
    CHECK_FALSE(setplay(ValuePair{4, 1}, std::nullopt));
}

TEST_CASE("set-play: the position itself unsolvable is NOT set play", "[themes][position]") {
    // A sentinel own-value must never be treated as some real D that a
    // sibling could sit one move below.
    CHECK_FALSE(setplay(ValuePair{DTM_UNSOLVABLE, 0}, ValuePair{1, 1}));
    CHECK_FALSE(setplay(ValuePair{DTM_INVALID, 0}, ValuePair{1, 1}));
    CHECK_FALSE(setplay(ValuePair{DTM_UNSET, 0}, ValuePair{1, 1}));
    // The boundary that actually exercises the `in.value.dtm <= DTM_MAX`
    // conjunct: DTM_UNSET (253) is exactly DTM_MAX (252) + 1, so
    // other.dtm + 1 == value.dtm arithmetically holds with a real,
    // in-range sibling. Without the conjunct this would read as a false
    // "yes"; with it, a sentinel own-value is never a real D.
    CHECK_FALSE(setplay(ValuePair{DTM_UNSET, 0}, ValuePair{DTM_MAX, 1}));
}

TEST_CASE("set-play: the DTM_MAX boundary itself", "[themes][position]") {
    // DTM_MAX (252) is the largest dtm a solved position can carry -- still
    // eligible as either side of the comparison.
    CHECK(setplay(ValuePair{DTM_MAX, 1}, ValuePair{DTM_MAX - 1, 1}));
    CHECK_FALSE(setplay(ValuePair{DTM_UNSET, 0}, ValuePair{DTM_MAX - 1, 1}));
}

TEST_CASE("set-play: no underflow when the position is itself mate (dtm 0)", "[themes][position]") {
    // dtm 0 means already mate. Nothing can be "one move before" mate, so
    // this must read as false -- and must not do so via value.dtm - 1
    // wrapping around to 255 (DTM_UNSOLVABLE) and accidentally matching an
    // unsolvable sibling. Written as other + 1 == value, this never
    // subtracts from value.dtm at all.
    CHECK_FALSE(setplay(ValuePair{0, 1}, ValuePair{DTM_UNSOLVABLE, 0}));
}

TEST_CASE("set-play is registered and needs the plane", "[themes][registry]") {
    const auto* t = find_theme("set-play");
    REQUIRE(t != nullptr);
    REQUIRE(t->needs == Needs::Plane);
}
