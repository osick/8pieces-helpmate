#include <catch2/catch_test_macros.hpp>
#include "generator/generator.h"
#include "generator/oracle.h"
#include "format/table_file.h"
#include "indexing/slice_index.h"
#include "chess/board.h"
#include <filesystem>
#include <random>
using namespace hm;
static std::string tdir() {
    auto d = std::filesystem::temp_directory_path() / "hm_gen_kqvk";
    std::filesystem::remove_all(d); std::filesystem::create_directories(d);
    return d.string();
}
static ValuePair probe_file(const std::string& dir, const std::string& fen) {
    auto b = Board::from_fen(fen); REQUIRE(b);
    Material m = Material::of(b->pieces());
    auto r = TableReader::open(dir + "/" + m.name() + ".hm"); REQUIRE(r);
    SliceIndex idx(m);
    auto e = idx.encode(b->pieces()); REQUIRE(e);
    return r->get(b->stm(), *e);
}
TEST_CASE("generate KQvk end to end") {
    GenOptions opt; opt.tables_dir = tdir();
    auto written = generate(*Material::parse("KQvk"), opt);
    REQUIRE(written.size() == 2);                     // Kvk then KQvk
    CHECK(std::filesystem::exists(opt.tables_dir + "/Kvk.hm"));
    CHECK(std::filesystem::exists(opt.tables_dir + "/KQvk.hm"));

    // goldens (hand-verified in Task 8)
    CHECK(probe_file(opt.tables_dir, "7k/6Q1/5K2/8/8/8/8/8 b - - 0 1").dtm == 0);
    CHECK(probe_file(opt.tables_dir, "7k/8/5K2/8/8/8/8/6Q1 w - - 0 1").dtm == 1);
    CHECK(probe_file(opt.tables_dir, "8/7k/5K2/8/8/8/8/6Q1 b - - 0 1").dtm == 2);
    CHECK(probe_file(opt.tables_dir, "8/7k/5K2/8/8/8/8/Q7 w - - 0 1").dtm == 3);

    // parity invariant + Kvk all unsolvable
    auto kvk = TableReader::open(opt.tables_dir + "/Kvk.hm");
    for (uint64_t c = 0; c < kvk->plane_size(); ++c) {
        CHECK(kvk->get(Color::White, c).dtm >= DTM_INVALID);
        CHECK(kvk->get(Color::Black, c).dtm >= DTM_INVALID);
    }
    auto kq = TableReader::open(opt.tables_dir + "/KQvk.hm");
    SliceIndex idx(*Material::parse("KQvk"));
    for (uint64_t c = 0; c < kq->plane_size(); ++c) {
        uint8_t w = kq->get(Color::White, c).dtm, b = kq->get(Color::Black, c).dtm;
        if (w <= DTM_MAX) CHECK(w % 2 == 1);
        if (b <= DTM_MAX) CHECK(b % 2 == 0);
    }

    // oracle cross-check on 300 random valid cells
    std::mt19937_64 rng(7);
    std::vector<PlacedPiece> pp;
    int checked = 0;
    while (checked < 300) {
        uint64_t c = rng() % kq->plane_size();
        Color stm = (rng() & 1) ? Color::White : Color::Black;
        uint8_t d = kq->get(stm, c).dtm;
        if (d == DTM_INVALID) continue;
        REQUIRE(idx.decode(c, pp));
        Board b = Board::from_pieces(pp, stm);
        auto o = oracle_solve(b, d <= DTM_MAX ? d : 16);
        if (d <= DTM_MAX) { REQUIRE(o); CHECK(o->dtm == d); }
        else               CHECK(!o);                 // unsolvable: no mate within 16 plies
        checked++;
    }
}
