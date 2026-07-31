#include <catch2/catch_test_macros.hpp>
#include "probe/tablebase.h"
#include "generator/generator.h"
#include <algorithm>
#include <filesystem>
#include <set>
using namespace hm;
static std::string gen_dir() {                        // one shared generated dir per test binary run
    static std::string dir = [] {
        auto d = std::filesystem::temp_directory_path() / "hm_probe";
        std::filesystem::remove_all(d); std::filesystem::create_directories(d);
        GenOptions opt; opt.tables_dir = d.string();
        generate(*Material::parse("KQvk"), opt);
        generate(*Material::parse("KPvk"), opt);
        return opt.tables_dir;
    }();
    return dir;
}
TEST_CASE("probe goldens with h-notation") {
    Tablebase tb(gen_dir());
    auto p = tb.probe("8/7k/5K2/8/8/8/8/6Q1 b - - 0 1");
    // dtm/count golden per Task 8 (cross-checked there against the cooperative
    // oracle): Black king has two legal replies (Kh6, Kh8); Kh6 allows three
    // distinct mates (Qg6#/Qh1#/Qh2#) and Kh8 allows one (Qg7#) -> count 4.
    REQUIRE(p); CHECK(p->dtm == 2); CHECK(p->count == 4); CHECK(!p->flipped);
    CHECK(Tablebase::h_notation(2, Color::Black) == "h#1");
    CHECK(Tablebase::h_notation(1, Color::White) == "h#0.5");
    CHECK(Tablebase::h_notation(0, Color::Black) == "h#0");
}
TEST_CASE("probe color-flipped position") {
    Tablebase tb(gen_dir());
    // color-flip of the dtm-2 golden: White king mated by black queen; only KQvk exists
    auto p = tb.probe("6q1/8/8/8/8/5k2/7K/8 w - - 0 1");
    REQUIRE(p); CHECK(p->dtm == 2); CHECK(p->flipped);
}
TEST_CASE("line reconstruction") {
    Tablebase tb(gen_dir());
    auto l = tb.line("8/7k/5K2/8/8/8/8/6Q1 b - - 0 1");
    // one of the 4 optimal lines (which one is found first depends on legal_moves()
    // ordering, not part of the golden); every optimal line here is King-then-mate.
    REQUIRE(l.size() == 2);
    CHECK((l[0] == "Kh6" || l[0] == "Kh8"));
    CHECK(l[1].back() == '#');
    std::set<std::string> mates = {"Qg6#", "Qh1#", "Qh2#", "Qg7#"};
    CHECK(mates.count(l[1]) == 1);

    auto all = tb.lines("8/7k/5K2/8/8/8/8/6Q1 b - - 0 1");
    CHECK(all.size() == 4);                            // count == 4 (see golden above)
    std::set<std::pair<std::string, std::string>> got;
    for (auto& ln : all) { REQUIRE(ln.size() == 2); got.insert({ln[0], ln[1]}); }
    std::set<std::pair<std::string, std::string>> want = {
        {"Kh6", "Qg6#"}, {"Kh6", "Qh1#"}, {"Kh6", "Qh2#"}, {"Kh8", "Qg7#"}};
    CHECK(got == want);

    auto promo = tb.lines("6k1/4P3/6K1/8/8/8/8/8 w - - 0 1");
    REQUIRE(promo.size() == 2);                        // e8=Q# and e8=R#
    std::set<std::string> promo_moves;
    for (auto& ln : promo) { REQUIRE(ln.size() == 1); promo_moves.insert(ln[0]); }
    CHECK(promo_moves == std::set<std::string>{"e8=Q#", "e8=R#"});
}
TEST_CASE("mine finds unique-solution cells") {
    Tablebase tb(gen_dir());
    int found = 0;
    tb.mine(*Material::parse("KQvk"), MineFilter{.dtm = 2, .count = 1}, [&](const std::string& fen) {
        auto p = tb.probe(fen);
        REQUIRE(p); CHECK(p->dtm == 2); CHECK(p->count == 1);
        return ++found < 10;
    });
    CHECK(found == 10);
}
TEST_CASE("errors") {
    Tablebase tb(gen_dir());
    // Neither material nor its color flip was built: KQvk/KPvk closures only ever
    // give White a single extra piece (KQvk, KRvk, KBvk, KNvk, KPvk, Kvk); a
    // bishop+knight for Black (and its flip, KBNvk for White) is outside that set.
    CHECK_THROWS_AS(tb.probe("8/8/8/6b1/3n4/4k3/8/4K3 w - - 0 1"), MissingTableError);
    CHECK_THROWS_AS(tb.probe("garbage"), std::invalid_argument);
    CHECK_THROWS_AS(tb.stats_json(*Material::parse("KRvkr")), MissingTableError);
}
TEST_CASE("unsolvable probes to nullopt") {
    Tablebase tb(gen_dir());
    CHECK(!tb.probe("8/8/8/8/8/4k3/8/4K3 w - - 0 1"));   // Kvk was built as part of closures
}
TEST_CASE("mine takes a MineFilter and behaves as before for dtm/count") {
    Tablebase tb(gen_dir());
    Material kqvk = *Material::parse("KQvk");

    std::vector<std::string> got;
    tb.mine(kqvk, MineFilter{.dtm = 2, .count = 4}, [&](const std::string& f) {
        got.push_back(f); return got.size() < 50;
    });
    REQUIRE_FALSE(got.empty());
    // every returned position really has dtm 2 and count 4
    for (const auto& f : got) {
        auto p = tb.probe(f);
        REQUIRE(p.has_value());
        CHECK(p->dtm == 2);
        CHECK(p->count == 4);
    }
    // the golden position from the "probe goldens" test above is among them, in its
    // canonical form: mine() emits one canonical representative per symmetry class,
    // while probe() (used above) accepts any of its 8 symmetric-equivalent FENs.
    CHECK(std::find(got.begin(), got.end(),
                    "8/8/8/8/8/2K5/7Q/1k6 b - - 0 1") != got.end());

    // count unset (-1) must not filter
    size_t any_count = 0;
    tb.mine(kqvk, MineFilter{.dtm = 2}, [&](const std::string&) {
        ++any_count; return any_count < 50; });
    CHECK(any_count >= got.size());
}
TEST_CASE("solution_shape counts distinct first and last moves") {
    Tablebase tb(gen_dir());

    // Golden KQvk position: 4 optimal lines -- Kh6 Qh2#, Kh6 Qh1#, Kh6 Qg6#, Kh8 Qg7#
    // => 2 distinct first moves (Kh6, Kh8), 4 distinct mating moves.
    auto sh = tb.solution_shape("8/7k/5K2/8/8/8/8/6Q1 b - - 0 1");
    CHECK(sh.exhaustive);
    CHECK(sh.starts == 2);
    CHECK(sh.ends == 4);

    // A position already mated (dtm 0) has no moves at all.
    auto mated = tb.solution_shape("8/8/8/8/8/8/8/kQK5 b - - 0 1");
    CHECK(mated.exhaustive);
    CHECK(mated.starts == 0);
    CHECK(mated.ends == 0);

    // Unsolvable position: bare kings.
    auto uns = tb.solution_shape("8/8/8/8/8/4k3/8/4K3 w - - 0 1");
    CHECK(uns.exhaustive);
    CHECK(uns.starts == 0);
    CHECK(uns.ends == 0);
}
