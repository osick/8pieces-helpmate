#include <catch2/catch_test_macros.hpp>
#include "format/block_codec.h"
#include "format/table_file.h"
#include "chess/types.h"
#include <numeric>
#include <random>
#include <stdexcept>
#include <vector>

using namespace hm;

TEST_CASE("block_count rounds up and handles an exact multiple") {
    CHECK(block_count(0, 1024) == 0);
    CHECK(block_count(1, 1024) == 1);
    CHECK(block_count(1024, 1024) == 1);
    CHECK(block_count(1025, 1024) == 2);
    // 4 * 7'751'073'792 = 31'004'295'168, which is an exact multiple of 65536,
    // so the ceiling division lands exactly on 473'088 (verified independently
    // in Python: 31004295168 / 65536 == 473088.0). The brief's literal here
    // (473'115) does not match that arithmetic; corrected to the true value.
    CHECK(block_count(4ull * 7'751'073'792ull, 65536) == 473'088ull);
}

TEST_CASE("a block round-trips byte for byte") {
    std::vector<uint8_t> src(65536);
    std::mt19937 rng(12345);
    for (auto& b : src) b = static_cast<uint8_t>(rng() & 0xFF);
    auto packed = compress_block(src.data(), src.size(), kDefaultZstdLevel);
    std::vector<uint8_t> back(src.size());
    decompress_block(packed.data(), packed.size(), back.data(), back.size());
    CHECK(back == src);
}

TEST_CASE("a constant block compresses hard and still round-trips") {
    // Half of a real 6-piece plane is DTM_INVALID; this is the case the whole
    // format exists to exploit, so it is pinned rather than assumed.
    std::vector<uint8_t> src(65536, DTM_INVALID);
    auto packed = compress_block(src.data(), src.size(), kDefaultZstdLevel);
    CHECK(packed.size() < src.size() / 50);
    std::vector<uint8_t> back(src.size());
    decompress_block(packed.data(), packed.size(), back.data(), back.size());
    CHECK(back == src);
}

TEST_CASE("a short final block round-trips at its own length") {
    // 4 * plane_size is not a multiple of 65536 in general.
    std::vector<uint8_t> src(1237);
    std::iota(src.begin(), src.end(), 0);
    auto packed = compress_block(src.data(), src.size(), kDefaultZstdLevel);
    std::vector<uint8_t> back(src.size());
    decompress_block(packed.data(), packed.size(), back.data(), back.size());
    CHECK(back == src);
}

TEST_CASE("a corrupt block throws instead of returning garbage") {
    std::vector<uint8_t> src(4096, 7);
    auto packed = compress_block(src.data(), src.size(), kDefaultZstdLevel);
    REQUIRE(packed.size() > 8);
    packed[packed.size() / 2] ^= 0xFF;          // flip a bit in the middle
    std::vector<uint8_t> back(src.size());
    CHECK_THROWS_AS(decompress_block(packed.data(), packed.size(), back.data(), back.size()),
                    std::runtime_error);
}

TEST_CASE("a block that decompresses to the wrong size throws") {
    std::vector<uint8_t> src(4096, 7);
    auto packed = compress_block(src.data(), src.size(), kDefaultZstdLevel);
    std::vector<uint8_t> back(2048);            // caller expects half
    CHECK_THROWS_AS(decompress_block(packed.data(), packed.size(), back.data(), back.size()),
                    std::runtime_error);
}
