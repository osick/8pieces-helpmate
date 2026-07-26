#include <catch2/catch_test_macros.hpp>
#include "generator/generator.h"
#include "format/table_file.h"
#include <filesystem>
#include <fstream>
using namespace hm;
static std::string file_bytes(const std::string& p) {
    std::ifstream f(p, std::ios::binary);
    return std::string(std::istreambuf_iterator<char>(f), {});
}
TEST_CASE("4-thread generation is byte-identical to 1-thread") {
    auto base = std::filesystem::temp_directory_path();
    for (int th : {1, 4}) {
        auto d = base / ("hm_thr_" + std::to_string(th));
        std::filesystem::remove_all(d); std::filesystem::create_directories(d);
        GenOptions opt; opt.tables_dir = d.string(); opt.threads = th;
        generate(*Material::parse("KPvk"), opt);
    }
    for (const char* n : {"Kvk", "KQvk", "KRvk", "KBvk", "KNvk", "KPvk"}) {
        auto a = file_bytes((base / "hm_thr_1" / (std::string(n) + ".hm")).string());
        auto b = file_bytes((base / "hm_thr_4" / (std::string(n) + ".hm")).string());
        REQUIRE(!a.empty());
        CHECK(a == b);
    }
}
