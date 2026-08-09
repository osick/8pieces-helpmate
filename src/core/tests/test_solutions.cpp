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

// KQvkq: the smallest material with two queens, which is what it takes to
// reach a real --starts/--ends SAN-vs-(from,to,promotion) divergence -- a
// single-queen material (KQvk) can never produce the disambiguation cases
// below (see the CRITICAL-1 regression test), nor the cross-solution AND
// case (see the "AND across solutions" regression test). ~13s to generate at
// --threads 4; shared (generated once) by every TEST_CASE that needs it.
std::string gen_kqvkq() {
    static std::string dir;
    if (dir.empty()) {
        dir = (std::filesystem::temp_directory_path() / "hm_solutions_test_kqvkq").string();
        std::filesystem::create_directories(dir);
        GenOptions opt;
        opt.tables_dir = dir;
        opt.threads = 4;
        generate(*Material::parse("KQvkq"), opt);
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
    // True KQvk dtm=2 totals (measured with an unbounded callback): mirror =
    // 477, mirror+model = 439. A cap of 400 sits BELOW both totals, so both
    // scans saturate at the same ceiling and the assertion degenerates to
    // "400 <= 400", which holds under any semantics including OR -- an OR
    // implementation would give mirror-or-model = 482 for KQvk, and 400 <=
    // 400 still passes without ever comparing 482 to anything. 700 clears
    // both true totals (matching the cap already used in "mine filters by
    // theme" above), so the assertion becomes the real "439 <= 477", which
    // holds for AND and fails for OR (482 > 477).
    size_t one = 0, both = 0;
    tb.mine(*m, MineFilter{.dtm = 2, .themes = {"mirror"}}, [&](const std::string&) {
        ++one;
        return one < 700;
    });
    tb.mine(*m, MineFilter{.dtm = 2, .themes = {"mirror", "model"}}, [&](const std::string&) {
        ++both;
        return both < 700;
    });
    REQUIRE(both <= one);
}

// IMPORTANT-2 regression: AND must hold ACROSS a position's solutions, not
// require both themes within the SAME solution. For KQvkq, positions showing
// mirror in SOME solution and model in SOME solution (any/any) number 13,090;
// positions showing both in the SAME solution number only 12,890 -- so an
// implementation that wrongly required both themes within one solution would
// still pass every other test in this file (they never exercise a position
// where the two counts diverge) while silently rejecting ~200 legitimate
// hits. This position is the reviewer-verified case where the two counts
// diverge: mirror appears in one optimal solution, model in a different one,
// never together in a single solution.
TEST_CASE("themes AND across solutions, not within one solution", "[themes][solutions]") {
    Tablebase tb(gen_kqvkq());
    auto m = Material::parse("KQvkq");
    REQUIRE(m);
    const char* fen = "8/8/8/8/5q2/2K5/4Q3/1k6 b - - 0 1";  // count 14

    auto sols = tb.solutions(fen, 100);
    REQUIRE(sols.size() == 14);
    bool any_mirror = false, any_model = false, same_solution_both = false;
    for (const auto& s : sols) {
        bool mi = themes::is_mirror(s), mo = themes::is_model(s);
        any_mirror = any_mirror || mi;
        any_model = any_model || mo;
        same_solution_both = same_solution_both || (mi && mo);
    }
    // The distinguishing property this test exists to pin: both themes show up
    // SOMEWHERE across the solution set, but never together in one solution.
    REQUIRE(any_mirror);
    REQUIRE(any_model);
    REQUIRE_FALSE(same_solution_both);

    auto p = tb.probe(fen);
    REQUIRE(p);
    REQUIRE(p->count == 14);

    // mine() emits CANONICAL fens (symmetry-reduced); compute this position's
    // canonical form the same way mine() does, via SliceIndex::encode/decode,
    // rather than hand-transcribing it.
    Board b = *Board::from_fen(fen);
    SliceIndex si(*m);
    auto idx = si.encode(b.pieces());
    REQUIRE(idx);
    std::vector<PlacedPiece> pp;
    REQUIRE(si.decode(*idx, pp));
    std::string canon = Board::from_pieces(pp, b.stm()).fen();

    // Direction 1 (accept): a position matching mirror-in-one-solution and
    // model-in-a-different-solution must be accepted by themes={"mirror",
    // "model"} -- correct per "any within a theme, AND across themes", which a
    // same-solution-required implementation would get wrong for exactly this
    // position.
    bool accepted = false;
    tb.mine(*m, MineFilter{.dtm = p->dtm, .count = p->count, .themes = {"mirror", "model"}},
            [&](const std::string& f) {
                if (f == canon) accepted = true;
                return true;
            });
    REQUIRE(accepted);

    // Direction 2 (reject): a position matching only "mirror" (mirror shown by
    // some solution, model shown by NO solution) must be excluded from the AND
    // result. Scan the same dtm/count bucket (narrow and cheap: filtered on
    // both dtm and count, not the whole material) for such a position and
    // confirm it is genuinely mirror-without-model, not merely absent because
    // of a bug.
    std::vector<std::string> mirror_hits;
    tb.mine(*m, MineFilter{.dtm = p->dtm, .count = p->count, .themes = {"mirror"}},
            [&](const std::string& f) {
                mirror_hits.push_back(f);
                return mirror_hits.size() < 500;
            });
    std::set<std::string> both_hits;
    tb.mine(*m, MineFilter{.dtm = p->dtm, .count = p->count, .themes = {"mirror", "model"}},
            [&](const std::string& f) {
                both_hits.insert(f);
                return true;
            });
    bool found_reject_case = false;
    for (const auto& f : mirror_hits) {
        if (both_hits.count(f)) continue;  // shows both -> not the "only A" case
        auto fsols = tb.solutions(f, 100);
        bool fm = false, fmo = false;
        for (const auto& s : fsols) {
            fm = fm || themes::is_mirror(s);
            fmo = fmo || themes::is_model(s);
        }
        REQUIRE(fm);  // it came from the mirror-filtered result, so mirror must hold somewhere
        if (!fmo) {   // model truly never holds: the clean "matching only A" case
            found_reject_case = true;
            break;
        }
    }
    REQUIRE(found_reject_case);
}

TEST_CASE("an unknown theme name is rejected, never ignored", "[themes][solutions]") {
    Tablebase tb(gen_kqvk());
    auto m = Material::parse("KQvk");
    REQUIRE_THROWS_AS(tb.mine(*m, MineFilter{.dtm = 2, .themes = {"nosuchtheme"}},
                              [](const std::string&) { return false; }),
                      std::invalid_argument);
}

// CRITICAL-1 regression: --ends is a released v0.6.2 feature keyed on SAN
// (distinct moves compared as rendered text), not on (from, to, promotion).
// KQvk (a single queen) can never exercise the divergence -- SAN differs from
// (from, to, promotion) only via a capture marker or a disambiguator, and
// KQvk has nothing to capture and no second piece of the same type to
// disambiguate against. KQvkq (two queens, a capturable one) is the smallest
// material that does. Both positions below are the reviewer's verified
// real-table divergence; mine()'s --ends filter must reproduce the v0.6.2
// (SAN-keyed) number, not the (from, to, promotion)-keyed one.
TEST_CASE("mine --ends stays SAN-keyed, not (from,to,promotion)-keyed", "[themes][solutions]") {
    Tablebase tb(gen_kqvkq());
    auto m = Material::parse("KQvkq");
    REQUIRE(m);

    auto check_ends = [&](const char* fen, int san_ends, int wrong_ends) {
        auto p = tb.probe(fen);
        REQUIRE(p);
        // Ground truth: solution_shape() always went through the SAN-based
        // path (lines()/shape_of) and was never touched by this task, so it
        // independently confirms the expected v0.6.2 value.
        auto sh = tb.solution_shape(fen);
        REQUIRE(sh.exhaustive);
        REQUIRE(sh.ends == san_ends);

        // Canonical form, the same way mine() builds its output FENs.
        Board b = *Board::from_fen(fen);
        SliceIndex si(*m);
        auto idx = si.encode(b.pieces());
        REQUIRE(idx);
        std::vector<PlacedPiece> pp;
        REQUIRE(si.decode(*idx, pp));
        std::string canon = Board::from_pieces(pp, b.stm()).fen();

        // mine() must place this position under --ends == the SAN value, and
        // NOT under the (from,to,promotion)-keyed value the bug produced.
        bool found_at_san = false, found_at_wrong = false;
        tb.mine(*m, MineFilter{.dtm = p->dtm, .count = p->count, .ends = san_ends},
                [&](const std::string& f) {
                    if (f == canon) found_at_san = true;
                    return true;
                });
        tb.mine(*m, MineFilter{.dtm = p->dtm, .count = p->count, .ends = wrong_ends},
                [&](const std::string& f) {
                    if (f == canon) found_at_wrong = true;
                    return true;
                });
        CHECK(found_at_san);
        CHECK_FALSE(found_at_wrong);
    };

    // Qxa4# and Qa4#: same (from,to) = d1->a4, differ only by the capture
    // marker. v0.6.2 (SAN-keyed): ends=2. Buggy (from,to,promotion)-keyed
    // code collapses them to ends=1.
    check_ends("8/8/8/8/8/1q6/8/k1KQ4 b - - 0 1", 2, 1);

    // Qb4-b1# and Qe4-b1#: different (from,to), both render as SAN "Qb1#".
    // v0.6.2 (SAN-keyed): ends=1. Buggy (from,to,promotion)-keyed code splits
    // them into ends=2.
    check_ends("8/8/8/8/8/8/2q5/K1k1Q3 b - - 0 1", 1, 2);
}

TEST_CASE("a solutions-free theme does not enumerate, so saturation cannot hide it", "[themes][mine]") {
    Tablebase tb(gen_kqvk());
    auto m = Material::parse("KQvk");
    REQUIRE(m);

    // Make the fixture dependency loud, not hidden: a Needs::Solutions theme
    // on the SAME filter must itself skip at least one saturated cell, or
    // the "skipped == 0" check below would hold for the wrong reason
    // (nothing to skip, rather than nothing enumerated) -- and a future
    // generator change that removes the saturated cell would let this test
    // keep passing while proving nothing. dtm=8 is used, not dtm=2: per
    // KQvk.stats.json's uniqueness histogram, KQvk's dtm=2 pool (580
    // positions) never saturates at all (max solution count observed there
    // is 7), while dtm=8 has 5273 saturated (count>=255) cells out of ~9000,
    // measured directly with an unbounded callback (3743 mirror matches, well
    // under the 10000 cap below, so the scan runs to completion either way).
    uint64_t skipped_solutions = 0;
    int solutions_hits = 0;
    tb.mine(
        *m, MineFilter{.dtm = 8, .themes = {"mirror"}},
        [&](const std::string&) {
            ++solutions_hits;
            return solutions_hits < 10000;
        },
        &skipped_solutions);
    REQUIRE(skipped_solutions > 0);

    MineFilter f;
    f.dtm = 8;
    f.themes = {"set-play"};
    uint64_t skipped = 0;
    int hits = 0;
    tb.mine(
        *m, f,
        [&](const std::string&) {
            ++hits;
            return hits < 50;
        },
        &skipped);
    // The whole point: nothing was skipped for saturation, because nothing was
    // enumerated -- set-play is Needs::Plane, one sibling-plane byte, never
    // `solutions`. A solutions-needing theme on the same table does skip.
    CHECK(skipped == 0);
}

// Regression guard for the sibling-plane wiring in mine(): the chunked
// read_values(other_stm, ...) call added for Needs::Plane themes must land on
// the SAME cell index as the queried plane, not a re-encoded or offset one. A
// wrong wiring would still emit plausible-looking FENs -- mine's own filter
// already restricts hits to legal, decodable, dtm-matching positions -- so
// the only thing that catches a wrong cell is checking the sibling plane
// independently, through a different code path (Tablebase::probe on the
// flipped position, not mine's chunk scan) against a real generated table.
TEST_CASE("mine's set-play scan reads the sibling plane at the correct cell", "[themes][mine]") {
    // KPvk, not KQvk: KPvk's 86,688 cells span two 65,536-cell scan chunks,
    // so chunk_base is nonzero for part of the scan -- a chunk-boundary bug
    // in the sibling-plane read (the other_stm read_values() call) would be
    // invisible on a single-chunk material like KQvk (29,568 cells) but not
    // here.
    Tablebase tb(gen_kpvk());
    auto m = Material::parse("KPvk");
    REQUIRE(m);

    std::vector<std::string> hits;
    tb.mine(*m, MineFilter{.dtm = 2, .themes = {"set-play"}}, [&](const std::string& f) {
        hits.push_back(f);
        return hits.size() < 200;
    });
    // Must not pass vacuously: KPvk's dtm=2 pool has 57 set-play hits out of
    // 69 positions total (measured directly via the CLI against a freshly
    // generated KPvk table), so an empty result here would mean the wiring is
    // broken, not that the theme is merely rare.
    REQUIRE_FALSE(hits.empty());

    for (const auto& f : hits) {
        auto b = Board::from_fen(f);
        REQUIRE(b);
        Board flipped = *b;
        flipped.reset(b->pieces(), b->stm() == Color::White ? Color::Black : Color::White);
        auto p = tb.probe(flipped.fen());
        REQUIRE(p.has_value());  // the sibling plane must be solvable
    }
}
