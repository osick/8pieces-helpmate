#include "themes/attack.h"
#include "chess/board.h"
#include <catch2/catch_test_macros.hpp>

using namespace hm;
using namespace hm::themes;

static std::vector<PlacedPiece> from_fen(const std::string& fen) {
    auto b = Board::from_fen(fen);
    REQUIRE(b);
    return b->pieces();
}

static int sq(const char* name) { return (name[1] - '1') * 8 + (name[0] - 'a'); }

TEST_CASE("king_field is the on-board neighbourhood", "[themes][attack]") {
    REQUIRE(king_field(sq("e4")).size() == 8);
    REQUIRE(king_field(sq("a1")).size() == 3);
    REQUIRE(king_field(sq("h8")).size() == 3);
    REQUIRE(king_field(sq("a4")).size() == 5);
}

TEST_CASE("sliders are blocked by intervening units", "[themes][attack]") {
    // White rook a1, white pawn a3: a3 blocks the file, so a5 is unattacked.
    auto ps = from_fen("8/8/8/8/8/P7/8/R3K2k w - - 0 1");
    REQUIRE(attackers_of(ps, Color::White, sq("a2")) == 1);
    REQUIRE(attackers_of(ps, Color::White, sq("a5")) == 0);
}

TEST_CASE("pawns attack diagonally, never forward", "[themes][attack]") {
    auto ps = from_fen("8/8/8/8/8/8/4P3/4K2k w - - 0 1");
    REQUIRE(attackers_of(ps, Color::White, sq("d3")) == 1);
    REQUIRE(attackers_of(ps, Color::White, sq("f3")) == 1);
    REQUIRE(attackers_of(ps, Color::White, sq("e3")) == 0);   // the push square
    REQUIRE(attackers_of(ps, Color::White, sq("e4")) == 0);
}

TEST_CASE("black pawns attack down the board", "[themes][attack]") {
    auto ps = from_fen("4k3/4p3/8/8/8/8/8/4K3 b - - 0 1");
    REQUIRE(attackers_of(ps, Color::Black, sq("d6")) == 1);
    REQUIRE(attackers_of(ps, Color::Black, sq("f6")) == 1);
    REQUIRE(attackers_of(ps, Color::Black, sq("e6")) == 0);
}

TEST_CASE("attackers are counted, not merely detected", "[themes][attack]") {
    // Rook a8 and rook h8 both bear on e8.
    auto ps = from_fen("R6R/8/8/8/8/8/8/4K2k w - - 0 1");
    REQUIRE(attackers_of(ps, Color::White, sq("e8")) == 2);
}

TEST_CASE("a pinned unit still counts as attacking", "[themes][attack]") {
    // White bishop c3 is pinned to Ke1 by the black rook on e-file... it still
    // controls its diagonal for the purpose of the black king's legality.
    auto ps = from_fen("8/8/8/8/8/2B5/8/4K2k w - - 0 1");
    REQUIRE(attackers_of(ps, Color::White, sq("e5")) == 1);
}

TEST_CASE("ignore_king_of unmasks the square behind the mated king",
          "[themes][attack]") {
    // White rook h1 checks the black king on h5. h6 is NOT a flight square --
    // the king cannot run along the checking line -- but with the king on the
    // board it blocks the ray and a naive scan reports h6 unattacked.
    auto ps = from_fen("8/8/8/7k/8/8/8/K6R b - - 0 1");
    REQUIRE(attackers_of(ps, Color::White, sq("h6")) == 0);
    REQUIRE(attackers_of(ps, Color::White, sq("h6"), Color::Black) == 1);
    // The king's own square is unaffected by removing the king.
    REQUIRE(attackers_of(ps, Color::White, sq("h5")) == 1);
}

TEST_CASE("piece_attacks isolates a single unit", "[themes][attack]") {
    auto ps = from_fen("R6R/8/8/8/8/8/8/4K2k w - - 0 1");
    PlacedPiece ra{{Color::White, PieceType::Rook}, (uint8_t)sq("a8")};
    PlacedPiece rh{{Color::White, PieceType::Rook}, (uint8_t)sq("h8")};
    REQUIRE(piece_attacks(ps, ra, sq("e8")));
    REQUIRE(piece_attacks(ps, rh, sq("e8")));
    REQUIRE_FALSE(piece_attacks(ps, ra, sq("e5")));
    REQUIRE_FALSE(piece_attacks(ps, ra, sq("a8")));   // never attacks its own square
}

TEST_CASE("knights jump over occupied squares", "[themes][attack]") {
    // Boxed-in knight on b2 still reaches d3. Note: the corner piece must NOT
    // be a pawn -- a white pawn on c2 attacks d3 diagonally in its own right,
    // which would make this fixture pass for the wrong reason (2 attackers,
    // not 1). A rook on c2 occupies the square without adding an attack.
    auto ps = from_fen("8/8/8/8/8/PPP5/PNR5/K1P4k w - - 0 1");
    REQUIRE(attackers_of(ps, Color::White, sq("d3")) == 1);   // the knight, boxed in
}
