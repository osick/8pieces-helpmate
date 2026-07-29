#include <catch2/catch_test_macros.hpp>
#include "generator/generator.h"
#include "generator/oracle.h"
#include "generator/eval.h"
#include "format/table_file.h"
#include "indexing/slice_index.h"
#include "chess/board.h"
#include <filesystem>
#include <random>
using namespace hm;
static std::string tdir(const char* name) {
    auto d = std::filesystem::temp_directory_path() / name;
    std::filesystem::remove_all(d); std::filesystem::create_directories(d);
    return d.string();
}
TEST_CASE("eval_board combines EP branch with table value") {
    // wK a1, bK a8, wP e5, bp d5; wtm with EP right on d6 (black just played d7-d5).
    Board b = Board::from_pieces({
        {{Color::White, PieceType::King}, 0},  {{Color::Black, PieceType::King}, 56},
        {{Color::White, PieceType::Pawn}, 36}, {{Color::Black, PieceType::Pawn}, 35}},
        Color::White, /*ep=*/43);
    REQUIRE(b.ep_square() == 43);
    // canned lookup: EP-less base value 9; position after exd6 e.p. valued 4.
    auto lookup = [&](Board& x) -> ValuePair {
        return x.pieces().size() == 4 ? ValuePair{9, 3} : ValuePair{4, 2};
    };
    ValuePair v = eval_board(b, lookup);
    CHECK((int)v.dtm == 5);                            // min(9, 1+4)
    CHECK((int)v.count == 2);                          // only the EP branch achieves 5
    // tie case: base 5 -> counts add up
    auto lookup2 = [&](Board& x) -> ValuePair {
        return x.pieces().size() == 4 ? ValuePair{5, 3} : ValuePair{4, 2};
    };
    ValuePair v2 = eval_board(b, lookup2);
    CHECK((int)v2.dtm == 5); CHECK((int)v2.count == 5);
}
TEST_CASE("pawn escaping check by capturing the checker still promotes") {
    // White King a1, Black King c2, White Knight e1 (checks the black king), Black
    // Pawn d2, Black to move. The ONLY way to answer the knight check is dxe1, and
    // since that lands on Black's promotion rank it must generate as a promotion
    // capture (four variants), never as a plain, non-promoting capture.
    Board b = Board::from_pieces({
        {{Color::White, PieceType::King}, 0},   {{Color::Black, PieceType::King}, 10},
        {{Color::White, PieceType::Knight}, 4}, {{Color::Black, PieceType::Pawn}, 11}},
        Color::Black);
    REQUIRE(b.in_check());
    int promo_captures = 0;
    for (const Move& m : b.legal_moves()) {
        if (m.from != 11 || m.to != 4) continue;         // only the d2xe1 capture matters here
        CHECK(m.promotion().has_value());                 // must never be a bare, non-promoting capture
        if (m.promotion()) promo_captures++;
    }
    CHECK(promo_captures == 4);                            // n, b, r, q
    // Playing the queen promotion must leave an actual queen on e1, not a pawn.
    for (const Move& m : b.legal_moves()) {
        if (m.from == 11 && m.to == 4 && m.promotion() == PieceType::Queen) {
            b.make(m);
            bool found_queen = false;
            for (auto& p : b.pieces())
                if (p.square == 4) { CHECK(p.piece.type == PieceType::Queen); found_queen = true; }
            CHECK(found_queen);
            b.unmake(m);
        }
    }
}
TEST_CASE("KPvk: promotions carry mate potential across slices") {
    GenOptions opt; opt.tables_dir = tdir("hm_gen_kpvk");
    generate(*Material::parse("KPvk"), opt);
    // KNvk and KBvk have no legal checkmate at all -> fully unsolvable
    for (const char* n : {"KNvk", "KBvk"}) {
        auto r = TableReader::open(opt.tables_dir + std::string("/") + n + ".hm"); REQUIRE(r);
        for (uint64_t c = 0; c < r->plane_size(); ++c) {
            CHECK(r->get(Color::White, c).dtm >= DTM_INVALID);
            CHECK(r->get(Color::Black, c).dtm >= DTM_INVALID);
        }
    }
    // KPvk itself is solvable ONLY via promotion (P alone can't mate) -> finite cells must exist
    auto r = TableReader::open(opt.tables_dir + "/KPvk.hm"); REQUIRE(r);
    uint64_t finite = 0;
    for (uint64_t c = 0; c < r->plane_size(); ++c)
        if (r->get(Color::White, c).dtm <= DTM_MAX) finite++;
    CHECK(finite > 0);
    // oracle cross-check on 200 random KPvk cells
    SliceIndex idx(*Material::parse("KPvk"));
    std::mt19937_64 rng(11); std::vector<PlacedPiece> pp; int checked = 0;
    while (checked < 200) {
        uint64_t c = rng() % r->plane_size();
        Color stm = (rng() & 1) ? Color::White : Color::Black;
        uint8_t d = r->get(stm, c).dtm;
        if (d > DTM_MAX) continue;                     // skip invalid/unsolvable (horizon issues)
        REQUIRE(idx.decode(c, pp));
        Board b = Board::from_pieces(pp, stm);
        auto o = oracle_solve(b, d);
        REQUIRE(o); CHECK(o->dtm == d);
        checked++;
    }
}
TEST_CASE("KPvkp: EP-relevant positions match the oracle", "[slow]") {
    GenOptions opt; opt.tables_dir = tdir("hm_gen_kpvkp");
    generate(*Material::parse("KPvkp"), opt);          // builds the full 36-slice closure
    auto r = TableReader::open(opt.tables_dir + "/KPvkp.hm"); REQUIRE(r);
    SliceIndex idx(*Material::parse("KPvkp"));
    // sample cells where a double push is available and pawns are on adjacent files
    std::mt19937_64 rng(13); std::vector<PlacedPiece> pp; int checked = 0;
    while (checked < 100) {
        uint64_t c = rng() % r->plane_size();
        if (!idx.decode(c, pp)) continue;
        int wp = -1, bp = -1;
        for (auto& p : pp) if (p.piece.type == PieceType::Pawn)
            (p.piece.color == Color::White ? wp : bp) = p.square;
        if (sq_rank(wp) != 1 || std::abs(sq_file(wp) - sq_file(bp)) != 1 || sq_rank(bp) != 3)
            continue;                                  // want: wP on rank 2, bp on rank 4 adjacent file
        for (Color stm : {Color::White, Color::Black}) {
            uint8_t d = r->get(stm, c).dtm;
            if (d > DTM_MAX) continue;
            Board b = Board::from_pieces(pp, stm);
            auto o = oracle_solve(b, d);
            REQUIRE(o); CHECK(o->dtm == d);            // oracle plays real EP; table used eval_board
        }
        checked++;
    }
}
