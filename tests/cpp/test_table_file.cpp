#include <catch2/catch_test_macros.hpp>
#include "format/table_file.h"
#include "indexing/material.h"
#include <cstring>
#include <filesystem>
#include <fstream>
#include <unistd.h>
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
TEST_CASE("marker tables expand to DTM_UNSOLVABLE without a payload") {
    namespace fs = std::filesystem;
    fs::path dir = fs::temp_directory_path() /
                   ("hm_marker_" + std::to_string(::getpid()));
    fs::create_directories(dir);
    std::string path = (dir / "KBvkq.hm").string();
    Material m = *Material::parse("KBvkq");
    const uint64_t ps = 1234;

    TableWriter::write_unsolvable(path, m, ps, R"({"material":"KBvkq"})");

    // A marker is tiny: header + JSON, no planes.
    CHECK(fs::file_size(path) < 512);

    auto r = TableReader::open(path);
    REQUIRE(r.has_value());
    CHECK(r->all_unsolvable());
    CHECK(r->plane_size() == ps);
    CHECK(r->material_name() == "KBvkq");
    CHECK(r->max_dtm() == DTM_UNSOLVABLE);
    for (uint64_t c : {uint64_t(0), ps / 2, ps - 1}) {
        auto v = r->get(Color::White, c);
        CHECK(v.dtm == DTM_UNSOLVABLE);
        CHECK(v.count == 0);
        CHECK(r->get(Color::Black, c).dtm == DTM_UNSOLVABLE);
    }
    CHECK_THROWS_AS(r->get(Color::White, ps), std::out_of_range);
    CHECK_THROWS_AS(r->get(Color::White, ~uint64_t(0)), std::out_of_range);
    fs::remove_all(dir);
}

TEST_CASE("ordinary tables stay format version 1 and keep reading") {
    namespace fs = std::filesystem;
    fs::path dir = fs::temp_directory_path() /
                   ("hm_v1_" + std::to_string(::getpid()));
    fs::create_directories(dir);
    std::string path = (dir / "Kvk.hm").string();
    std::vector<uint8_t> dw(4, 7), db(4, 8), cw(4, 1), cb(4, 2);
    TableWriter::write(path, *Material::parse("Kvk"), 4, 7, "{}",
                       dw.data(), db.data(), cw.data(), cb.data());

    std::ifstream in(path, std::ios::binary);
    TableHeader hdr{};
    in.read(reinterpret_cast<char*>(&hdr), sizeof(hdr));
    CHECK(hdr.version == 1);
    CHECK((hdr.flags & 0x01) == 0);

    auto r = TableReader::open(path);
    REQUIRE(r.has_value());
    CHECK_FALSE(r->all_unsolvable());
    CHECK(r->get(Color::White, 0).dtm == 7);
    CHECK(r->get(Color::Black, 3).dtm == 8);
    fs::remove_all(dir);
}
