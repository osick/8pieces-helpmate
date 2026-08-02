#include "format/block_codec.h"

#include <stdexcept>
#include <string>

#include <zstd.h>

namespace hm {

uint64_t block_count(uint64_t logical_size, uint32_t block_size) {
    if (block_size == 0) throw std::runtime_error("block_count: block_size is zero");
    return (logical_size + block_size - 1) / block_size;
}

size_t max_compressed_size(size_t n) { return ZSTD_compressBound(n); }

std::vector<uint8_t> compress_block(const uint8_t* src, size_t n, int level) {
    std::vector<uint8_t> out(ZSTD_compressBound(n));
    size_t written = ZSTD_compress(out.data(), out.size(), src, n, level);
    if (ZSTD_isError(written))
        throw std::runtime_error(std::string("zstd compress failed: ") +
                                  ZSTD_getErrorName(written));
    out.resize(written);
    return out;
}

void decompress_block(const uint8_t* src, size_t n, uint8_t* dst, size_t dst_capacity) {
    size_t got = ZSTD_decompress(dst, dst_capacity, src, n);
    if (ZSTD_isError(got))
        throw std::runtime_error(std::string("zstd decompress failed: ") +
                                  ZSTD_getErrorName(got));
    // A block that decompresses to a different length than the caller expects
    // means the index and the payload disagree -- a corrupt or truncated file,
    // not a recoverable condition.
    if (got != dst_capacity)
        throw std::runtime_error("zstd decompress: expected " + std::to_string(dst_capacity) +
                                  " bytes, got " + std::to_string(got));
}

}  // namespace hm
