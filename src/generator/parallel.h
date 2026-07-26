#pragma once
#include <algorithm>
#include <cstdint>
#include <functional>
#include <thread>
#include <vector>

namespace hm {

// Splits [0,n) into contiguous chunks over `threads` std::threads (1 -> inline call).
// fn(begin, end) must only write to cells it owns and shared atomics.
inline void parallel_for(uint64_t n, int threads, const std::function<void(uint64_t, uint64_t)>& fn) {
    if (threads <= 1 || n == 0) { fn(0, n); return; }
    uint64_t chunk = (n + (uint64_t)threads - 1) / (uint64_t)threads;
    std::vector<std::thread> workers;
    for (int t = 0; t < threads; ++t) {
        uint64_t begin = (uint64_t)t * chunk;
        if (begin >= n) break;
        uint64_t end = std::min(n, begin + chunk);
        workers.emplace_back(fn, begin, end);
    }
    for (auto& w : workers) w.join();
}

}  // namespace hm
