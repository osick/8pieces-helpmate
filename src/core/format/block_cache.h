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
// The cache never hands out a pointer into its storage. An entry can be
// evicted by another thread the moment the lock is released, so any pointer
// returned to a caller would be a use-after-free waiting to happen. There is
// therefore no lifetime rule to document: every access copies the byte it
// needs out while holding the lock.
class BlockCache {
public:
    BlockCache(size_t capacity_blocks, uint32_t block_size);

    // Returns one byte from block `index` at `offset`, calling `fill(dst,
    // len)` to decompress the block only on a miss. `fill` is invoked without
    // the lock held, so multiple threads may decompress the same block
    // concurrently on a racing miss; that is deliberate -- it trades a rare
    // duplicated decompression for never blocking one thread on another's
    // (potentially slow) fill. Implemented on top of read_range below.
    uint8_t byte_at(uint64_t index, size_t offset, size_t len,
                    const std::function<void(uint8_t*, size_t)>& fill);

    // Copies `count` bytes starting at `offset` within block `index` (whose
    // decompressed length is `len`) into `dst`, locking once per call rather
    // than once per byte. Same fill/miss contract as byte_at. A range caller
    // (TableReader::read_range, streaming a re-block conversion) uses this
    // instead of looping byte_at so a 16-64 KB span costs one mutex
    // acquisition and one memcpy, not thousands of each.
    void read_range(uint64_t index, size_t offset, size_t count, size_t len, uint8_t* dst,
                    const std::function<void(uint8_t*, size_t)>& fill);

    size_t fills() const;
    size_t hits() const;
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
    size_t hits_ = 0;
};

}  // namespace hm
