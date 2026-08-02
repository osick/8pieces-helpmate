#pragma once
#include <cstddef>
#include <cstdint>
#include <functional>
#include <list>
#include <mutex>
#include <unordered_map>
#include <vector>

namespace hm {

// A bounded LRU of decompressed blocks. Mutex-guarded because generation is
// multi-threaded and a TableReader may be probed concurrently.
//
// Lifetime rule: the pointer returned by get_or_fill is valid only until the
// next call to get_or_fill on the SAME cache (from any thread) that could
// evict the entry it points into. Copy the bytes you need out before making
// another call -- do not hold the pointer across it. This is safe in
// TableReader::get because the byte is copied out immediately after the
// call returns.
class BlockCache {
public:
    BlockCache(size_t capacity_blocks, uint32_t block_size);

    // Returns a pointer to `len` decompressed bytes for `index`, calling
    // `fill(dst, len)` only on a miss.
    const uint8_t* get_or_fill(uint64_t index, const std::function<void(uint8_t*, size_t)>& fill, size_t len);

    size_t fills() const;
    size_t capacity() const { return cap_; }

private:
    struct Entry {
        uint64_t index;
        std::vector<uint8_t> data;
    };

    size_t cap_;
    uint32_t block_size_;
    mutable std::mutex mu_;
    std::list<Entry> lru_;  // front = most recent
    std::unordered_map<uint64_t, std::list<Entry>::iterator> map_;
    size_t fills_ = 0;
};

}  // namespace hm
