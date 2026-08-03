#include <catch2/catch_test_macros.hpp>

#include "probe/solution.h"
#include "themes/mate_themes.h"

using namespace hm;
using namespace hm::themes;

// A mate-position detector reads only the final board, so a Solution with a
// start position and no plies is a complete input. No table file needed.
static Solution at(const std::string& fen) {
    auto b = Board::from_fen(fen);
    REQUIRE(b);
    return Solution{*b, {}};
}

// Every fixture below descends from one back-rank mate: black Kg8, white Ra8
// checking along the 8th, white Kg6 covering f7/g7/h7. The rook covers f8 and
// -- once the mated king is lifted off g8 -- h8 behind it. Each of the five
// field squares is therefore denied exactly once, which is what purity asks.
static constexpr const char* kBase = "R5k1/8/6K1/8/8/8/8/8 b - - 0 1";

TEST_CASE("a back-rank mate by rook and king is pure", "[themes][mate]") {
    auto s = at(kBase);
    REQUIRE(final_board(s).state() == PosState::Checkmate);
    REQUIRE(is_pure(s));
}

TEST_CASE("double check is impure", "[themes][mate]") {
    // Base plus a white knight on e7, which also bears on g8. Of the knight's
    // other squares (c6, c8, d5, f5, g6) none is a field square, so the king's
    // square being attacked twice is the ONLY thing purity can object to here.
    auto s = at("R5k1/4N3/6K1/8/8/8/8/8 b - - 0 1");
    REQUIRE(final_board(s).state() == PosState::Checkmate);
    REQUIRE_FALSE(is_pure(s));
}

TEST_CASE("an over-guarded flight square is impure", "[themes][mate]") {
    // Near-miss: the base mate plus a white knight on f5, whose only bearing on
    // the king's field is a second, redundant guard of g7. Single check still,
    // mate unchanged, but g7 is now denied for two reasons.
    auto doubled = at("R5k1/8/6K1/5N2/8/8/8/8 b - - 0 1");
    REQUIRE(final_board(doubled).state() == PosState::Checkmate);
    REQUIRE(is_pure(at(kBase)));
    REQUIRE_FALSE(is_pure(doubled));
}

TEST_CASE("a black unit on an attacked field square is double duty", "[themes][mate]") {
    // A black rook on h8 blocks that flight square AND h8 is attacked by Ra8
    // through the king: the square is unavailable for two reasons at once,
    // which breaks purity. The rook cannot parry the check (g8 blocks its own
    // rank), so the position is still mate.
    auto s = at("R5kr/8/6K1/8/8/8/8/8 b - - 0 1");
    REQUIRE(final_board(s).state() == PosState::Checkmate);
    REQUIRE_FALSE(is_pure(s));
}

TEST_CASE("mirror mate: the whole king field is empty", "[themes][mate]") {
    REQUIRE(is_mirror(at(kBase)));
    // Near-miss: the black rook on h8 stands beside its king.
    REQUIRE_FALSE(is_mirror(at("R5kr/8/6K1/8/8/8/8/8 b - - 0 1")));
}

TEST_CASE("model mate: every white officer participates", "[themes][mate]") {
    auto s = at(kBase);
    REQUIRE(is_model(s));
    // Near-miss: an idle white bishop on h1. Its diagonal runs g2-b7 to the
    // rook on a8 and touches no square of the king's field, so the mate stays
    // pure while the bishop contributes nothing.
    auto idle = at("R5k1/8/6K1/8/8/8/8/7B b - - 0 1");
    REQUIRE(final_board(idle).state() == PosState::Checkmate);
    REQUIRE(is_pure(idle));
    REQUIRE_FALSE(is_model(idle));
}

TEST_CASE("model exempts the white king and white pawns", "[themes][mate]") {
    // A white pawn on a2 does nothing -- it bears only on b3 -- and must not
    // break model-ness.
    auto s = at("R5k1/8/6K1/8/8/8/P7/8 b - - 0 1");
    REQUIRE(final_board(s).state() == PosState::Checkmate);
    REQUIRE(is_pure(s));
    REQUIRE(is_model(s));
    REQUIRE_FALSE(is_ideal(s));  // ideal exempts nothing
}

TEST_CASE("ideal mate: no exemptions at all", "[themes][mate]") {
    auto s = at(kBase);
    REQUIRE(is_model(s));
    REQUIRE(is_ideal(s));  // Ra8 checks, Kg6 covers f7/g7/h7, nothing idle
}

TEST_CASE("a black unit off the king field breaks ideal", "[themes][mate]") {
    // A black pawn on a7 is not adjacent to its king, so it does not
    // participate. It cannot parry the check either -- a7-a6 and a7-a5 leave
    // the king attacked -- so the position remains mate.
    auto s = at("R5k1/p7/6K1/8/8/8/8/8 b - - 0 1");
    REQUIRE(final_board(s).state() == PosState::Checkmate);
    REQUIRE(is_model(s));
    REQUIRE_FALSE(is_ideal(s));
}

TEST_CASE("a white unit on a field square blocks it with its body", "[themes][mate]") {
    // A different mate: black Kh8, Rh1 checking up the h-file, white Ng8 sitting
    // on a flight square and white Kf7 guarding g7 (and covering the knight, so
    // Kxg8 is illegal). g8 is guarded as well as occupied, but a WHITE body is
    // not double duty -- the square is denied once, by the knight standing on
    // it. The knight participates by occupation, so this is model and ideal
    // too, and it is not mirror because the field is not empty.
    auto s = at("6Nk/5K2/8/8/8/8/8/7R b - - 0 1");
    REQUIRE(final_board(s).state() == PosState::Checkmate);
    REQUIRE(is_pure(s));
    REQUIRE(is_model(s));
    REQUIRE(is_ideal(s));
    REQUIRE_FALSE(is_mirror(s));
}

TEST_CASE("a self-blocked but unattacked field square is not double duty", "[themes][mate]") {
    // The textbook back-rank mate: black Kg8 walled in by its own pawns on f7,
    // g7 and h7, Ra8 mating along the 8th, white king parked on a1. Each pawn
    // square is denied for exactly ONE reason -- the pawn -- because White
    // attacks none of them, so this is pure. Not ideal, though: the white king
    // on a1 contributes nothing.
    auto s = at("R5k1/5ppp/8/8/8/8/8/K7 b - - 0 1");
    REQUIRE(final_board(s).state() == PosState::Checkmate);
    REQUIRE(is_pure(s));
    REQUIRE(is_model(s));
    REQUIRE_FALSE(is_ideal(s));
    REQUIRE_FALSE(is_mirror(s));
}

TEST_CASE("an unguarded flight square is not pure", "[themes][mate]") {
    // Same rook check with the pawns and the guarding king gone: f7, g7 and h7
    // are simply free, so this is check and not mate. A detector fed a position
    // that leaks must say no rather than mistake "not attacked twice" for pure.
    auto s = at("R5k1/8/8/8/8/8/8/K7 b - - 0 1");
    REQUIRE(final_board(s).state() == PosState::Check);
    REQUIRE_FALSE(is_pure(s));
}

TEST_CASE("ideal implies model implies pure", "[themes][mate]") {
    for (const char* fen : {"R5k1/8/6K1/8/8/8/8/8 b - - 0 1", "R5k1/8/6K1/8/8/8/P7/8 b - - 0 1",
                            "R5kr/8/6K1/8/8/8/8/8 b - - 0 1", "R5k1/4N3/6K1/8/8/8/8/8 b - - 0 1"}) {
        auto s = at(fen);
        if (is_ideal(s)) REQUIRE(is_model(s));
        if (is_model(s)) REQUIRE(is_pure(s));
    }
}

TEST_CASE("a position with no black king detects nothing", "[themes][mate]") {
    // Board::from_fen insists on one king per side, so build this board
    // directly: Ke1 and Ra1, White to move, no black king anywhere. The
    // detectors must answer false rather than read past the missing king.
    Solution s{
        Board::from_pieces({{{Color::White, PieceType::King}, 4}, {{Color::White, PieceType::Rook}, 0}},
                           Color::White, -1),
        {}};
    REQUIRE_FALSE(is_pure(s));
    REQUIRE_FALSE(is_model(s));
    REQUIRE_FALSE(is_ideal(s));
    REQUIRE_FALSE(is_mirror(s));
}
