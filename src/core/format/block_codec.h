#pragma once
#include <cstddef>
#include <cstdint>
#include <vector>

namespace hm {

// Blocks are compressed INDEPENDENTLY. A single stream would compress better
// but destroy random access, which is the whole point of the table format.
// Does NOT detect overflow: (logical_size + block_size - 1) wraps for
// logical_size near UINT64_MAX (e.g. block_count(UINT64_MAX, 65536) == 0).
// Real tables never approach this, but callers deriving logical_size from an
// untrusted header (e.g. mmap'd file input) must bound-check it themselves
// before calling.
uint64_t block_count(uint64_t logical_size, uint32_t block_size);
size_t max_compressed_size(size_t n);
std::vector<uint8_t> compress_block(const uint8_t* src, size_t n, int level);
// Throws std::runtime_error if the block is corrupt or does not decompress to
// exactly dst_capacity bytes.
void decompress_block(const uint8_t* src, size_t n, uint8_t* dst, size_t dst_capacity);

}  // namespace hm
