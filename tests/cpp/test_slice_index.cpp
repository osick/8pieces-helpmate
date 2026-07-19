#include <catch2/catch_test_macros.hpp>
#include "indexing/slice_index.h"
#include "indexing/material.h"
#include <random>
#include <tuple>
using namespace hm;
TEST_CASE("plane sizes") {
    CHECK(SliceIndex(*Material::parse("Kvk")).size()   == 462);
    CHECK(SliceIndex(*Material::parse("KQvk")).size()  == 462ull * 64);
    CHECK(SliceIndex(*Material::parse("KPvk")).size()  == 1806ull * 48);
    CHECK(SliceIndex(*Material::parse("KQvkq")).size() == 462ull * 64 * 64);
    CHECK(SliceIndex(*Material::parse("KPvkp")).size() == 1806ull * 48 * 48);
}
static std::vector<PlacedPiece> transform_pos(const std::vector<PlacedPiece>& pp, int t) {
    auto out = pp; for (auto& p : out) p.square = (uint8_t)transform_sq(p.square, t); return out;
}
TEST_CASE("all symmetry images share one canonical index (pawnless)") {
    SliceIndex idx(*Material::parse("KQvkr"));
    std::vector<PlacedPiece> pp = {
        {{Color::White, PieceType::King}, 12}, {{Color::White, PieceType::Queen}, 33},
        {{Color::Black, PieceType::King}, 60}, {{Color::Black, PieceType::Rook}, 7}};
    auto base = idx.encode(pp); REQUIRE(base);
    for (int t = 1; t < 8; ++t) CHECK(idx.encode(transform_pos(pp, t)) == base);
}
TEST_CASE("mirror image shares canonical index (pawns)") {
    SliceIndex idx(*Material::parse("KPvkp"));
    std::vector<PlacedPiece> pp = {
        {{Color::White, PieceType::King}, 4},  {{Color::White, PieceType::Pawn}, 28},
        {{Color::Black, PieceType::King}, 20}, {{Color::Black, PieceType::Pawn}, 35}};
    auto base = idx.encode(pp); REQUIRE(base);
    CHECK(idx.encode(transform_pos(pp, 1)) == base);
}
TEST_CASE("decode/encode round trip over random cells") {
    for (auto name : {"KQvkr", "KPvkp", "KQQvk"}) {
        SliceIndex idx(*Material::parse(name));
        std::mt19937_64 rng(42);
        std::vector<PlacedPiece> pp;
        int checked = 0;
        while (checked < 2000) {
            uint64_t c = rng() % idx.size();
            if (!idx.decode(c, pp)) continue;         // overlapping cell
            auto e = idx.encode(pp);
            REQUIRE(e);
            CHECK(*e <= c);                           // canonical is minimal
            checked++;
        }
    }
}
TEST_CASE("identical pieces: swapped order encodes identically") {
    SliceIndex idx(*Material::parse("KQQvk"));
    std::vector<PlacedPiece> a = {
        {{Color::White, PieceType::King}, 0}, {{Color::White, PieceType::Queen}, 10},
        {{Color::White, PieceType::Queen}, 20}, {{Color::Black, PieceType::King}, 63}};
    auto b = a; std::swap(b[1], b[2]);
    CHECK(idx.encode(a) == idx.encode(b));
}
TEST_CASE("encode rejects garbage") {
    SliceIndex idx(*Material::parse("KQvk"));
    std::vector<PlacedPiece> wrong = {
        {{Color::White, PieceType::King}, 0}, {{Color::Black, PieceType::King}, 63}};
    CHECK(!idx.encode(wrong));                        // material mismatch (missing Q)
    std::vector<PlacedPiece> adj = {
        {{Color::White, PieceType::King}, 0}, {{Color::White, PieceType::Queen}, 30},
        {{Color::Black, PieceType::King}, 1}};
    CHECK(!idx.encode(adj));                          // adjacent kings
}
