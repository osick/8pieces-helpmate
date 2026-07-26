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
    tb.mine(*Material::parse("KQvk"), 2, 1, [&](const std::string& fen) {
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
