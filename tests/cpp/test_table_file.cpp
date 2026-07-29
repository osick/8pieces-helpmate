#include <catch2/catch_test_macros.hpp>
#include "format/table_file.h"
#include "indexing/material.h"
#include <cstring>
#include <filesystem>
#include <fstream>
using namespace hm;
TEST_CASE("header is 64 bytes") { CHECK(sizeof(TableHeader) == 64); }
TEST_CASE("write/read round trip") {
    auto dir = std::filesystem::temp_directory_path() / "hm_test_tables";
    std::filesystem::create_directories(dir);
    auto path = (dir / "KQvk.hm").string();
    const uint64_t n = 1000;
    std::vector<uint8_t> dw(n), db(n), cw(n), cb(n);
    for (uint64_t i = 0; i < n; ++i) { dw[i] = i % 250; db[i] = (i * 7) % 250; cw[i] = i % 3; cb[i] = 1; }
    TableWriter::write(path, *Material::parse("KQvk"), n, 42, "{\"hello\":1}",
                       dw.data(), db.data(), cw.data(), cb.data());
    auto r = TableReader::open(path);
    REQUIRE(r);
    CHECK(r->plane_size() == n); CHECK(r->max_dtm() == 42);
    CHECK(r->material_name() == "KQvk");
    CHECK(r->meta_json() == "{\"hello\":1}");
    for (uint64_t i : {0ull, 1ull, 500ull, 999ull}) {
        CHECK(r->get(Color::White, i).dtm == dw[i]); CHECK(r->get(Color::White, i).count == cw[i]);
        CHECK(r->get(Color::Black, i).dtm == db[i]); CHECK(r->get(Color::Black, i).count == cb[i]);
    }
    CHECK(!TableReader::open((dir / "missing.hm").string()));
}
TEST_CASE("reader rejects a header with an overflow-crafted plane_size") {
    auto dir = std::filesystem::temp_directory_path() / "hm_test_tables";
    std::filesystem::create_directories(dir);
    auto path = (dir / "overflow.hm").string();
    TableHeader hdr{};
    std::memcpy(hdr.magic, "HM8P", 4);
    hdr.version = 1;
    hdr.encoding = 1;
    hdr.symmetry = 1;
    std::memcpy(hdr.material, "Kvk", 3);
    hdr.plane_size = (1ull << 62);  // 4 * plane_size overflows uint64_t
    hdr.max_dtm = 0;
    hdr.json_len = 0;
    {
        std::ofstream out(path, std::ios::binary | std::ios::trunc);
        out.write(reinterpret_cast<const char*>(&hdr), sizeof(hdr));
    }
    CHECK(!TableReader::open(path));
}
TEST_CASE("reader rejects a truncated file") {
    auto dir = std::filesystem::temp_directory_path() / "hm_test_tables";
    std::filesystem::create_directories(dir);
    auto path = (dir / "trunc.hm").string();
    const uint64_t n = 100;
    std::vector<uint8_t> p(n, 1);
    TableWriter::write(path, *Material::parse("Kvk"), n, 5, "{}", p.data(), p.data(), p.data(), p.data());
    auto sz = std::filesystem::file_size(path);
    std::filesystem::resize_file(path, sz - 3);
    CHECK(!TableReader::open(path));
}
