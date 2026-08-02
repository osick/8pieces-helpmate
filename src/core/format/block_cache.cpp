#include "format/block_cache.h"

#include <cstring>
#include <stdexcept>

namespace hm {

BlockCache::BlockCache(size_t capacity_blocks, uint32_t block_size)
    : cap_(capacity_blocks ? capacity_blocks : 1), block_size_(block_size) {}

uint8_t BlockCache::byte_at(uint64_t index, size_t offset, size_t len,
                            const std::function<void(uint8_t*, size_t)>& fill) {
    if (offset >= len) throw std::runtime_error("BlockCache: offset out of range");
    uint8_t b;
    read_range(index, offset, 1, len, &b, fill);
    return b;
}

void BlockCache::read_range(uint64_t index, size_t offset, size_t count, size_t len, uint8_t* dst,
                            const std::function<void(uint8_t*, size_t)>& fill) {
    if (len > block_size_) throw std::runtime_error("BlockCache: len exceeds block_size");
    if (offset + count > len) throw std::runtime_error("BlockCache: range out of block bounds");
    if (count == 0) return;

    {
        std::lock_guard<std::mutex> lock(mu_);
        auto it = map_.find(index);
        if (it != map_.end()) {
            lru_.splice(lru_.begin(), lru_, it->second);  // promote to most-recent
            ++hits_;
            std::memcpy(dst, lru_.front().data.data() + offset, count);
            return;
        }
    }

    // Miss: decompress into a local buffer with no lock held, so a slow fill
    // (up to a 64 KB decompression) never blocks another thread's probe.
    // Another thread may race us and decompress the same block too -- that
    // is fine.
    std::vector<uint8_t> local(len);
    fill(local.data(), len);

    std::lock_guard<std::mutex> lock(mu_);
    ++fills_;
    auto it = map_.find(index);
    if (it != map_.end()) {
        // Another thread inserted this index while we were decompressing.
        // Use its entry and discard our redundant copy.
        lru_.splice(lru_.begin(), lru_, it->second);
        std::memcpy(dst, lru_.front().data.data() + offset, count);
        return;
    }
    if (lru_.size() >= cap_) {
        map_.erase(lru_.back().index);
        lru_.pop_back();
    }
    lru_.push_front(Entry{index, std::move(local)});
    map_[index] = lru_.begin();
    std::memcpy(dst, lru_.front().data.data() + offset, count);
}

size_t BlockCache::fills() const {
    std::lock_guard<std::mutex> lock(mu_);
    return fills_;
}

size_t BlockCache::hits() const {
    std::lock_guard<std::mutex> lock(mu_);
    return hits_;
}

}  // namespace hm
