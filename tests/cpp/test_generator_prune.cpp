#include "generator/generator.h"
#include "indexing/material.h"
#include <catch2/catch_test_macros.hpp>

using namespace hm;

TEST_CASE("slice_has_any_mate finds mates only where they exist") {
    // KQvk: the queen mates the bare king cooperatively — mates exist.
    CHECK(slice_has_any_mate(*Material::parse("KQvk")));
    // Bare white king cannot even give check.
    CHECK_FALSE(slice_has_any_mate(*Material::parse("Kvk")));
    CHECK_FALSE(slice_has_any_mate(*Material::parse("Kvkq")));
    // King+bishop against king+queen: a queen on the blocking square can always
    // interpose or capture, so no mate position exists (user's KBvk[qr]* class).
    CHECK_FALSE(slice_has_any_mate(*Material::parse("KBvkq")));
    // King+knight against king+bishop does have mates (KNvkb is solvable).
    CHECK(slice_has_any_mate(*Material::parse("KNvkb")));
}

#include "format/table_file.h"
#include <filesystem>
#include <fstream>

TEST_CASE("generate prunes provably unsolvable slices") {
    namespace fs = std::filesystem;
    fs::path dir = fs::temp_directory_path() /
                   ("hm_prune_" + std::to_string(::getpid()));
    fs::remove_all(dir);
    GenOptions opt;
    opt.tables_dir = dir.string();
    opt.threads = 2;

    generate(*Material::parse("Kvkq"), opt);            // whole closure: Kvk, Kvkq

    for (const char* n : {"Kvk", "Kvkq"}) {
        auto r = TableReader::open((dir / (std::string(n) + ".hm")).string());
        REQUIRE(r.has_value());
        INFO("slice " << n);
        CHECK(r->all_unsolvable());                     // bare king: pruned structurally
        CHECK(fs::file_size((dir / (std::string(n) + ".hm")).string()) < 4096);
        CHECK(r->get(Color::White, 0).dtm == DTM_UNSOLVABLE);
    }
    fs::remove_all(dir);
}

TEST_CASE("generate prunes KBvkq via the recursive successors-dead rule") {
    namespace fs = std::filesystem;

    // KBvkq is NOT caught by the trivial mating_side_is_bare_king() disjunct
    // (white holds a bishop) -- proves this test exercises the recursive
    // branch (successors_dead && !slice_has_any_mate) instead.
    REQUIRE_FALSE(Material::parse("KBvkq")->mating_side_is_bare_king());
    REQUIRE_FALSE(slice_has_any_mate(*Material::parse("KBvkq")));

    fs::path a = fs::temp_directory_path() / ("hm_kbvkq_pruned_" + std::to_string(::getpid()));
    fs::path b = fs::temp_directory_path() / ("hm_kbvkq_full_" + std::to_string(::getpid()));
    fs::remove_all(a); fs::remove_all(b);

    GenOptions on;  on.tables_dir = a.string();  on.threads = 2;  on.prune = true;
    generate(*Material::parse("KBvkq"), on);

    auto pruned = TableReader::open((a / "KBvkq.hm").string());
    REQUIRE(pruned.has_value());
    CHECK(pruned->all_unsolvable());                      // successors (KBvk, Kvkq, ...) all dead
    CHECK(fs::file_size((a / "KBvkq.hm").string()) < 4096);
    fs::remove_all(a);

    // Full (unpruned) generation of the same slice -- real ~1.9M-cell run,
    // expected to take single-digit seconds. Verifies the recursive verdict
    // above matches what actual generation computes for every cell.
    GenOptions off; off.tables_dir = b.string(); off.threads = 2; off.prune = false;
    generate(*Material::parse("KBvkq"), off);

    auto full = TableReader::open((b / "KBvkq.hm").string());
    REQUIRE(full.has_value());
    CHECK_FALSE(full->all_unsolvable());
    REQUIRE(pruned->plane_size() == full->plane_size());
    // Parity over every LEGAL cell: KBvkq has genuine DTM_INVALID cells
    // (illegal placements / non-canonical duplicates / opponent-in-check),
    // and a marker's get() collapses invalid *and* unsolvable into a
    // uniform DTM_UNSOLVABLE by design (see the comment on the marker
    // metadata in generate()). So the meaningful claim -- and the one that
    // actually validates the recursive verdict -- is that every legal
    // position the full generator computed has no finite-DTM solution
    // either, i.e. pruned and full agree everywhere full isn't DTM_INVALID.
    uint64_t legal_checked = 0;
    for (uint64_t c = 0; c < full->plane_size(); ++c)
        for (Color stm : {Color::White, Color::Black}) {
            uint8_t full_dtm = full->get(stm, c).dtm;
            if (full_dtm == DTM_INVALID) continue;
            REQUIRE(pruned->get(stm, c).dtm == full_dtm);
            ++legal_checked;
        }
    CHECK(legal_checked > 0);          // sanity: the exclusion above didn't skip everything
    fs::remove_all(b);
}

TEST_CASE("generate leaves solvable slices byte-identical when pruning") {
    namespace fs = std::filesystem;
    fs::path a = fs::temp_directory_path() / ("hm_pr_on_" + std::to_string(::getpid()));
    fs::path b = fs::temp_directory_path() / ("hm_pr_off_" + std::to_string(::getpid()));
    fs::remove_all(a); fs::remove_all(b);

    GenOptions on;  on.tables_dir = a.string();  on.threads = 2;  on.prune = true;
    GenOptions off; off.tables_dir = b.string(); off.threads = 2; off.prune = false;
    generate(*Material::parse("KQvk"), on);
    generate(*Material::parse("KQvk"), off);

    auto bytes = [](const fs::path& p) {
        std::ifstream in(p, std::ios::binary);
        return std::vector<char>(std::istreambuf_iterator<char>(in), {});
    };
    CHECK(bytes(a / "KQvk.hm") == bytes(b / "KQvk.hm"));   // solvable: untouched
    // Kvk is unsolvable, so only the unpruned run writes a full table.
    auto pruned = TableReader::open((a / "Kvk.hm").string());
    auto full   = TableReader::open((b / "Kvk.hm").string());
    REQUIRE(pruned.has_value()); REQUIRE(full.has_value());
    CHECK(pruned->all_unsolvable());
    CHECK_FALSE(full->all_unsolvable());
    REQUIRE(pruned->plane_size() == full->plane_size());
    for (uint64_t c = 0; c < full->plane_size(); ++c)      // same values, both sides
        for (Color stm : {Color::White, Color::Black})
            REQUIRE(pruned->get(stm, c).dtm == full->get(stm, c).dtm);
    fs::remove_all(a); fs::remove_all(b);
}

TEST_CASE("derived prune rule reproduces the known unsolvable classes", "[slow]") {
    namespace fs = std::filesystem;
    fs::path dir = fs::temp_directory_path() /
                   ("hm_oracle_" + std::to_string(::getpid()));
    fs::remove_all(dir);
    GenOptions opt; opt.tables_dir = dir.string(); opt.threads = 4;

    // Generating these roots covers their whole closures, i.e. every material
    // named below.
    for (const char* root : {"KBvkqr", "KNvkq", "KNvkr", "KBvkb", "KNvkb"})
        generate(*Material::parse(root), opt);

    auto is_unsolvable = [&](const char* n) {
        auto r = TableReader::open((dir / (std::string(n) + ".hm")).string());
        REQUIRE(r.has_value());
        return r->max_dtm() == DTM_UNSOLVABLE;
    };

    // Kvk*: bare king. KBvk[qr]*: bishop vs queens/rooks. KNvk[q]*: knight vs queens.
    for (const char* n : {"Kvk", "Kvkq", "Kvkr", "Kvkqr",
                          "KBvk", "KBvkq", "KBvkr", "KBvkqr",
                          "KNvk", "KNvkq"}) {
        INFO("expected unsolvable: " << n);
        CHECK(is_unsolvable(n));
    }
    // Counter-oracle: neighbouring materials that DO have helpmates.
    for (const char* n : {"KNvkr", "KBvkb", "KNvkb"}) {
        INFO("expected solvable: " << n);
        CHECK_FALSE(is_unsolvable(n));
    }
    fs::remove_all(dir);
}
