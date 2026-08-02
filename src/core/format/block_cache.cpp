#include "format/block_cache.h"

#include <stdexcept>

namespace hm {

BlockCache::BlockCache(size_t capacity_blocks, uint32_t block_size)
    : cap_(capacity_blocks ? capacity_blocks : 1), block_size_(block_size) {}

const uint8_t* BlockCache::get_or_fill(uint64_t index, const std::function<void(uint8_t*, size_t)>& fill,
                                       size_t len) {
    if (len > block_size_) throw std::runtime_error("BlockCache: len exceeds block_size");
    std::lock_guard<std::mutex> lock(mu_);
    auto it = map_.find(index);
    if (it != map_.end()) {
        lru_.splice(lru_.begin(), lru_, it->second);  // promote to most-recent
        return lru_.front().data.data();
    }
    if (lru_.size() >= cap_) {
        map_.erase(lru_.back().index);
        lru_.pop_back();
    }
    lru_.push_front(Entry{index, std::vector<uint8_t>(len)});
    map_[index] = lru_.begin();
    ++fills_;
    fill(lru_.front().data.data(), len);
    return lru_.front().data.data();
}

size_t BlockCache::fills() const {
    std::lock_guard<std::mutex> lock(mu_);
    return fills_;
}

}  // namespace hm
