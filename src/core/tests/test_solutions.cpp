#include <catch2/catch_test_macros.hpp>
#include <filesystem>
#include <set>

#include "generator/generator.h"
#include "probe/solution.h"
#include "probe/tablebase.h"
#include "themes/mate_themes.h"
#include "themes/registry.h"

using namespace hm;

// The golden KQvk position: dtm 2, count 4, four known optimal solutions.
// Already pinned by tests across the C++, Python and CLI suites.
static const char* kGolden = "8/7k/5K2/8/8/8/8/6Q1 b - - 0 1";

namespace {
std::string gen_kqvk() {
    static std::string dir;
    if (dir.empty()) {
        dir = (std::filesystem::temp_directory_path() / "hm_solutions_test").string();
        std::filesystem::create_directories(dir);
        GenOptions opt;
        opt.tables_dir = dir;
        generate(*Material::parse("KQvk"), opt);
    }
    return dir;
}

// KPvk: the smallest material whose optimal lines actually promote (a bare
// pawn can't mate on its own -- see test_generator_pawns.cpp). Same closure
// shape as test_probe.cpp's gen_dir(), just isolated to this binary's own
// temp dir.
std::string gen_kpvk() {
    static std::string dir;
    if (dir.empty()) {
        dir = (std::filesystem::temp_directory_path() / "hm_solutions_test_kpvk").string();
        std::filesystem::create_directories(dir);
        GenOptions opt;
        opt.tables_dir = dir;
        generate(*Material::parse("KPvk"), opt);
    }
    return dir;
}

// KQvkn: the smallest material whose optimal lines contain a real capture.
// A capture needs a 4th board piece to remove, and any such piece pulls in a
// full 462*64*64 slice regardless of which piece it is -- KPvkp (captures AND
// en passant) is >36 slices and takes minutes even at 4 threads (see
// test_generator_pawns.cpp's [slow] tag), so it's excluded by the "keep
// generation cheap" rule. A single extra piece per side (no pawns, so no
// promotion-driven sub-slice explosion) is the cheapest material that still
// exercises `captured`; --threads 4 keeps it to ~15s instead of ~45s.
std::string gen_kqvkn() {
    static std::string dir;
    if (dir.empty()) {
        dir = (std::filesystem::temp_directory_path() / "hm_solutions_test_kqvkn").string();
        std::filesystem::create_directories(dir);
        GenOptions opt;
        opt.tables_dir = dir;
        opt.threads = 4;
        generate(*Material::parse("KQvkn"), opt);
    }
    return dir;
}
}  // namespace

TEST_CASE("solutions() mirrors lines() one-for-one", "[themes][solutions]") {
    Tablebase tb(gen_kqvk());
    auto ls = tb.lines(kGolden, 100);
    auto ss = tb.solutions(kGolden, 100);
    REQUIRE(ss.size() == ls.size());
    REQUIRE(ss.size() == 4);
    for (size_t i = 0; i < ss.size(); ++i) REQUIRE(ss[i].plies.size() == ls[i].size());
}

TEST_CASE("every solution carries the queried position as start", "[themes][solutions]") {
    Tablebase tb(gen_kqvk());
    for (const auto& s : tb.solutions(kGolden, 100)) REQUIRE(s.start.fen() == kGolden);
}

TEST_CASE("the last ply of every optimal solution is mate", "[themes][solutions]") {
    Tablebase tb(gen_kqvk());
    for (const auto& s : tb.solutions(kGolden, 100)) {
        REQUIRE(!s.plies.empty());
        REQUIRE(s.plies.back().is_check);
        REQUIRE(final_board(s).state() == PosState::Checkmate);
    }
}

TEST_CASE("plies record the moving unit and its from/to", "[themes][solutions]") {
    Tablebase tb(gen_kqvk());
    auto ss = tb.solutions(kGolden, 100);
    for (const auto& s : ss) {
        // h#1: Black moves first, then White mates.
        REQUIRE(s.plies.size() == 2);
        REQUIRE(s.plies[0].piece.color == Color::Black);
        REQUIRE(s.plies[0].piece.type == PieceType::King);
        REQUIRE(s.plies[1].piece.color == Color::White);
        for (const auto& p : s.plies) {
            REQUIRE(p.from != p.to);
            REQUIRE_FALSE(p.captured.has_value());  // no captures in this material
            REQUIRE_FALSE(p.promotion.has_value());
            REQUIRE_FALSE(p.is_ep);
        }
    }
}

TEST_CASE("a position that is already mate yields one empty solution", "[themes][solutions]") {
    Tablebase tb(gen_kqvk());
    const char* mated = "8/8/8/8/8/8/8/kQK5 b - - 0 1";  // dtm 0
    auto ss = tb.solutions(mated, 100);
    REQUIRE(ss.size() == 1);
    REQUIRE(ss[0].plies.empty());
    REQUIRE(final_board(ss[0]).fen() == mated);  // start is the mate
}

TEST_CASE("solutions() rejects a bad FEN the same way lines() does", "[themes][solutions]") {
    Tablebase tb(gen_kqvk());
    REQUIRE_THROWS_AS(tb.solutions("garbage", 10), std::invalid_argument);
}

// KQvk's material has no pawns, so the tests above only ever assert
// `promotion`/`captured`/`is_ep` absent. Positively exercise the promotion
// branch with the same KPvk promotion golden used by test_probe.cpp's "line
// reconstruction" test: White king g6, pawn e7, Black king g8, White to move.
// e8=Q# and e8=R# are the two dtm-1 optimal replies (h#0.5, count 2); e8=N#
// and e8=B# fall a ply short of check-and-mate-in-one, so they don't tie.
TEST_CASE("a promoting ply reports the promoted-to piece type", "[themes][solutions]") {
    Tablebase tb(gen_kpvk());
    const char* fen = "6k1/4P3/6K1/8/8/8/8/8 w - - 0 1";
    auto ss = tb.solutions(fen, 100);
    REQUIRE(ss.size() == 2);
    std::set<PieceType> promos;
    for (const auto& s : ss) {
        REQUIRE(s.plies.size() == 1);
        const Ply& p = s.plies[0];
        REQUIRE(p.promotion.has_value());
        REQUIRE_FALSE(p.captured.has_value());  // promotion, not a capture
        REQUIRE_FALSE(p.is_ep);
        REQUIRE(p.is_check);
        promos.insert(*p.promotion);
    }
    CHECK(promos == std::set<PieceType>{PieceType::Queen, PieceType::Rook});
}

// KQvkn is the cheapest material (see gen_kqvkn() above) whose optimal lines
// contain a genuine capture. White king c1, queen c2, Black king a1, knight
// b1, White to move: probe confirms dtm 1, count 2 -- Qxb1# (captures the
// knight) and Qb2# (no capture) tie as optimal mates in one ply. This
// positively exercises the `captured` branch in collect_solutions rather than
// only ever asserting it absent.
TEST_CASE("a capturing ply reports the captured piece type", "[themes][solutions]") {
    Tablebase tb(gen_kqvkn());
    const char* fen = "8/8/8/8/8/8/2Q5/knK5 w - - 0 1";
    auto ss = tb.solutions(fen, 100);
    REQUIRE(ss.size() == 2);
    int capturing = 0, quiet = 0;
    for (const auto& s : ss) {
        REQUIRE(s.plies.size() == 1);
        const Ply& p = s.plies[0];
        REQUIRE(p.is_check);
        REQUIRE_FALSE(p.promotion.has_value());
        REQUIRE_FALSE(p.is_ep);
        if (p.captured.has_value()) {
            CHECK(*p.captured == PieceType::Knight);  // the only capturable piece here
            ++capturing;
        } else {
            ++quiet;
        }
    }
    CHECK(capturing == 1);
    CHECK(quiet == 1);
}

// En passant remains uncovered here. Exercising `is_ep`/the EP branch of
// `captured` needs a black pawn double push followed by a white EP capture
// inside an OPTIMAL line, which needs at least one pawn per side on the
// board -- i.e. KPvkp, the minimal material for it. KPvkp's full 36-slice
// closure (test_generator_pawns.cpp) does not finish in minutes even at
// --threads 4 (measured while writing this test: still running after 5
// minutes), so it fails both the "cheap generation" and "no [slow] tests"
// constraints for this suite. No smaller material can reach en passant, so
// this branch is knowingly left untested rather than faked.

TEST_CASE("shape_of_solutions agrees with the SAN-based shape_of", "[themes][solutions]") {
    Tablebase tb(gen_kqvk());
    auto ls = tb.lines(kGolden, 100);
    auto ss = tb.solutions(kGolden, 100);
    SolutionShape from_san = shape_of(4, ls);
    SolutionShape from_plies = shape_of_solutions(4, ss);
    REQUIRE(from_plies.starts == from_san.starts);
    REQUIRE(from_plies.ends == from_san.ends);
    REQUIRE(from_plies.exhaustive == from_san.exhaustive);
}

TEST_CASE("a saturated count is never enumerated", "[themes][solutions]") {
    REQUIRE_FALSE(shape_of_solutions((int)COUNT_SAT, {}).exhaustive);
}

TEST_CASE("mine filters by theme", "[themes][solutions]") {
    Tablebase tb(gen_kqvk());
    auto m = Material::parse("KQvk");
    REQUIRE(m);

    // KQvk's whole dtm=2 pool is 580 positions, of which 477 show `mirror`
    // (measured directly: `mine(dtm=2)` vs `mine(dtm=2, themes={"mirror"})`
    // with an unbounded callback). The brief's original cap of 400 sits below
    // BOTH totals, so both scans saturate at the same ceiling and the
    // intended "477 < 580" difference never surfaces -- that is a fixture
    // defect (cap chosen too low relative to the true totals), not a filter
    // bug: with only three pieces on the board (white king, white queen,
    // black king), `mirror` genuinely fails only when the mating queen lands
    // adjacent to the black king (a contact mate), which is common enough
    // that ~18% of positions are excluded. 700 clears both true totals so the
    // scans terminate naturally instead of both hitting the same cap.
    std::vector<std::string> unfiltered, mirrored;
    tb.mine(*m, MineFilter{.dtm = 2}, [&](const std::string& f) {
        unfiltered.push_back(f);
        return unfiltered.size() < 700;
    });
    tb.mine(*m, MineFilter{.dtm = 2, .themes = {"mirror"}}, [&](const std::string& f) {
        mirrored.push_back(f);
        return mirrored.size() < 700;
    });

    REQUIRE_FALSE(unfiltered.empty());
    REQUIRE_FALSE(mirrored.empty());
    REQUIRE(mirrored.size() < unfiltered.size());  // the filter must bite
    // Every hit really shows the theme.
    for (const auto& f : mirrored) {
        auto sols = tb.solutions(f, 100);
        bool any = false;
        for (const auto& s : sols)
            if (themes::is_mirror(s)) any = true;
        REQUIRE(any);
    }
}

TEST_CASE("multiple themes AND together", "[themes][solutions]") {
    Tablebase tb(gen_kqvk());
    auto m = Material::parse("KQvk");
    size_t one = 0, both = 0;
    tb.mine(*m, MineFilter{.dtm = 2, .themes = {"mirror"}}, [&](const std::string&) {
        ++one;
        return one < 400;
    });
    tb.mine(*m, MineFilter{.dtm = 2, .themes = {"mirror", "model"}}, [&](const std::string&) {
        ++both;
        return both < 400;
    });
    REQUIRE(both <= one);
}

TEST_CASE("an unknown theme name is rejected, never ignored", "[themes][solutions]") {
    Tablebase tb(gen_kqvk());
    auto m = Material::parse("KQvk");
    REQUIRE_THROWS_AS(tb.mine(*m, MineFilter{.dtm = 2, .themes = {"nosuchtheme"}},
                              [](const std::string&) { return false; }),
                      std::invalid_argument);
}
