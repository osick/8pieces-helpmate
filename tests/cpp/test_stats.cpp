#include <catch2/catch_test_macros.hpp>
#include "generator/generator.h"
#include "format/table_file.h"
#include "chess/board.h"
#include <nlohmann/json.hpp>
#include <filesystem>
#include <fstream>
using namespace hm;
TEST_CASE("stats sidecar is written and consistent") {
    auto d = std::filesystem::temp_directory_path() / "hm_stats";
    std::filesystem::remove_all(d); std::filesystem::create_directories(d);
    GenOptions opt; opt.tables_dir = d.string();
    generate(*Material::parse("KQvk"), opt);
    std::ifstream f(opt.tables_dir + "/KQvk.stats.json"); REQUIRE(f.good());
    auto j = nlohmann::json::parse(f);
    CHECK(j["material"] == "KQvk");
    CHECK(j["plane_size"] == 462ull * 64);
    int maxd = j["max_dtm"];
    CHECK(maxd >= 3);                                  // golden G3 proves >= 3
    // histogram sums must account for every cell
    uint64_t total_b = 0;
    for (auto& [k, v] : j["dtm_histogram"]["btm"].items()) total_b += (uint64_t)v;
    total_b += (uint64_t)j["cells"]["invalid"]["btm"] + (uint64_t)j["cells"]["unsolvable"]["btm"];
    CHECK(total_b == 462ull * 64);
    // deepest FENs probe back to max_dtm
    REQUIRE(!j["deepest"].empty());
    auto b = Board::from_fen(j["deepest"][0]); REQUIRE(b);
    auto r = TableReader::open(opt.tables_dir + "/KQvk.hm");
    SliceIndex idx(*Material::parse("KQvk"));
    CHECK((int)r->get(b->stm(), *idx.encode(b->pieces())).dtm == maxd);
    // embedded meta == sidecar
    CHECK(nlohmann::json::parse(r->meta_json()) == j);
    // uniqueness histogram exists for some depth
    CHECK(j.contains("uniqueness"));
}
