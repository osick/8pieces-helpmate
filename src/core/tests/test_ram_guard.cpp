#include <catch2/catch_test_macros.hpp>
#include "generator/generator.h"
#include "indexing/material.h"
#include "indexing/slice_index.h"
using namespace hm;

// The guard decision is a pure function (required, available) -> ok/error, so
// the "would refuse a 30 GB slice" behavior is testable without a 30 GB box.

TEST_CASE("plane_ram_bytes is 4 planes x plane_size") {
    CHECK(plane_ram_bytes(0) == 0);
    CHECK(plane_ram_bytes(462) == 4ull * 462);                    // Kvk
    CHECK(plane_ram_bytes(462ull * 64 * 64 * 64 * 64) ==          // KQRvkqr-sized
          4ull * 462 * 64 * 64 * 64 * 64);
}

TEST_CASE("ram_guard_error refuses when required exceeds available") {
    uint64_t required = plane_ram_bytes(462ull * 64 * 64 * 64 * 64);  // ~28.9 GiB
    uint64_t available = 8ull << 30;                                  // 8 GiB
    auto err = ram_guard_error("KQRvkqr", required, available);
    REQUIRE(err);
    CHECK(err->find("KQRvkqr") != std::string::npos);             // names the slice
    CHECK(err->find("GiB") != std::string::npos);                 // sizes in GiB
    CHECK(err->find("--force-ram") != std::string::npos);         // names the override
}

TEST_CASE("ram_guard_error passes when required fits") {
    CHECK(!ram_guard_error("Kvk", 100, 200));
    CHECK(!ram_guard_error("Kvk", 200, 200));                     // boundary: == is ok
    CHECK(ram_guard_error("Kvk", 201, 200));                      // boundary: one over
}

TEST_CASE("tiny slices pass the guard against this machine's real MemAvailable") {
    auto avail = mem_available_bytes();
    if (!avail) return;                                            // unreadable: guard is skipped anyway
    CHECK(*avail > 0);
    for (auto name : {"Kvk", "KQvk", "KPvkp"}) {
        uint64_t req = plane_ram_bytes(SliceIndex(*Material::parse(name)).size());
        CHECK(!ram_guard_error(name, req, *avail));
    }
}
