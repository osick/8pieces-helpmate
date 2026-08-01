#include <catch2/catch_test_macros.hpp>
#include "generator/generator.h"
#include "generator/oracle.h"
#include "format/table_file.h"
#include "indexing/slice_index.h"
#include "chess/board.h"
#include <filesystem>
#include <random>
using namespace hm;
TEST_CASE("KQvk counts match the oracle") {
    auto d = std::filesystem::temp_directory_path() / "hm_counts";
    std::filesystem::remove_all(d); std::filesystem::create_directories(d);
    GenOptions opt; opt.tables_dir = d.string();
    generate(*Material::parse("KQvk"), opt);
    auto r = TableReader::open(opt.tables_dir + "/KQvk.hm"); REQUIRE(r);
    SliceIndex idx(*Material::parse("KQvk"));

    // goldens (hand-verified in Task 8)
    auto probe = [&](const std::string& fen) {
        auto b = Board::from_fen(fen); REQUIRE(b);
        return r->get(b->stm(), *idx.encode(b->pieces()));
    };
    CHECK((int)probe("7k/6Q1/5K2/8/8/8/8/8 b - - 0 1").count == 1);   // dtm 0
    CHECK((int)probe("7k/8/5K2/8/8/8/8/6Q1 w - - 0 1").count == 1);   // dtm 1
    CHECK((int)probe("8/7k/5K2/8/8/8/8/6Q1 b - - 0 1").count == 4);   // dtm 2, golden G2 (Task 8 correction)

    // structural invariants + oracle cross-check
    std::mt19937_64 rng(23); std::vector<PlacedPiece> pp; int checked = 0;
    for (uint64_t c = 0; c < r->plane_size(); ++c)
        for (Color stm : {Color::White, Color::Black}) {
            ValuePair v = r->get(stm, c);
            if (v.dtm > DTM_MAX) CHECK((int)v.count == 0);
            else                 CHECK((int)v.count >= 1);
        }
    while (checked < 150) {
        uint64_t c = rng() % r->plane_size();
        Color stm = (rng() & 1) ? Color::White : Color::Black;
        ValuePair v = r->get(stm, c);
        if (v.dtm > DTM_MAX) continue;
        REQUIRE(idx.decode(c, pp));
        Board b = Board::from_pieces(pp, stm);
        auto o = oracle_solve(b, v.dtm);
        REQUIRE(o);
        CHECK(o->count == (int)v.count);              // both saturate at 255
        checked++;
    }
}
TEST_CASE("promotion mate counts Q and R separately") {
    auto d = std::filesystem::temp_directory_path() / "hm_counts_p";
    std::filesystem::remove_all(d); std::filesystem::create_directories(d);
    GenOptions opt; opt.tables_dir = d.string();
    generate(*Material::parse("KPvk"), opt);
    auto r = TableReader::open(opt.tables_dir + "/KPvk.hm"); REQUIRE(r);
    SliceIndex idx(*Material::parse("KPvk"));
    auto b = Board::from_fen("6k1/4P3/6K1/8/8/8/8/8 w - - 0 1"); REQUIRE(b);
    ValuePair v = r->get(Color::White, *idx.encode(b->pieces()));
    CHECK((int)v.dtm == 1);
    CHECK((int)v.count == 2);                         // e8=Q# and e8=R# (golden G4)
}
