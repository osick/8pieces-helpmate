#include <catch2/catch_test_macros.hpp>

#include "chess/board.h"
#include "themes/attack.h"

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
    REQUIRE(attackers_of(ps, Color::White, sq("e3")) == 0);  // the push square
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

TEST_CASE("a queen attacks along rank, file, and diagonal", "[themes][attack]") {
    // Queen a1, white king a8 (far from every test square so it never adds a
    // second attacker), black king h8. The queen is the only piece exercising
    // both slider directions, so all three lines need their own assertion.
    auto ps = from_fen("K6k/8/8/8/8/8/8/Q7 w - - 0 1");
    REQUIRE(attackers_of(ps, Color::White, sq("d1")) == 1);  // rank 1, b1/c1 clear
    REQUIRE(attackers_of(ps, Color::White, sq("a4")) == 1);  // a-file, a2/a3 clear
    REQUIRE(attackers_of(ps, Color::White, sq("d4")) == 1);  // a1-d4 diagonal
}

TEST_CASE("a pinned unit still counts as attacking", "[themes][attack]") {
    // White bishop e4 is absolutely pinned along the e-file: black rook e8,
    // nothing between it and the bishop (e7/e6/e5 empty), bishop e4, nothing
    // between it and the white king (e3/e2 empty), white king e1. The bishop
    // cannot legally move off the file, yet it still controls its diagonal --
    // attackers_of does no legality analysis, so d5 must still read as attacked.
    auto ps = from_fen("4r2k/8/8/8/4B3/8/8/4K3 w - - 0 1");
    REQUIRE(attackers_of(ps, Color::White, sq("d5")) == 1);
}

TEST_CASE("ignore_king_of unmasks the square behind the mated king", "[themes][attack]") {
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
    REQUIRE_FALSE(piece_attacks(ps, ra, sq("a8")));  // never attacks its own square
}

TEST_CASE("piece_attacks is blocked by an intervening unit", "[themes][attack]") {
    // Rook a1, pawn a3: aligned with a5 by file, but the pawn sits between them.
    auto ps = from_fen("8/8/8/8/8/P7/8/R3K2k w - - 0 1");
    PlacedPiece ra{{Color::White, PieceType::Rook}, (uint8_t)sq("a1")};
    REQUIRE_FALSE(piece_attacks(ps, ra, sq("a5")));
}

TEST_CASE("knights jump over occupied squares", "[themes][attack]") {
    // Boxed-in knight on b2 still reaches d3. Note: the corner piece must NOT
    // be a pawn -- a white pawn on c2 attacks d3 diagonally in its own right,
    // which would make this fixture pass for the wrong reason (2 attackers,
    // not 1). A rook on c2 occupies the square without adding an attack.
    auto ps = from_fen("8/8/8/8/8/PPP5/PNR5/K1P4k w - - 0 1");
    REQUIRE(attackers_of(ps, Color::White, sq("d3")) == 1);  // the knight, boxed in
}
