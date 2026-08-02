#pragma once
#include <cstddef>
#include <cstdint>
#include <vector>

namespace hm {

// Blocks are compressed INDEPENDENTLY. A single stream would compress better
// but destroy random access, which is the whole point of the table format.
// Overflow-free by construction (division-based, not (logical_size +
// block_size - 1) / block_size), so callers do not need to pre-check
// logical_size before calling, including when it is derived from an
// untrusted header (e.g. mmap'd file input).
uint64_t block_count(uint64_t logical_size, uint32_t block_size);
size_t max_compressed_size(size_t n);
std::vector<uint8_t> compress_block(const uint8_t* src, size_t n, int level);
// Throws std::runtime_error if the block is corrupt or does not decompress to
// exactly dst_capacity bytes.
void decompress_block(const uint8_t* src, size_t n, uint8_t* dst, size_t dst_capacity);

}  // namespace hm
