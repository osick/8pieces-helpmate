#pragma once
#include <algorithm>
#include <cstdint>
#include <exception>
#include <functional>
#include <mutex>
#include <thread>
#include <vector>

namespace hm {

// Splits [0,n) into contiguous chunks over `threads` std::threads (1 -> inline call).
// fn(begin, end) must only write to cells it owns and shared atomics.
// An exception thrown by fn on any worker is captured and rethrown on the
// calling thread after every started worker has been joined (workers never
// escape unjoined, and a worker's exception can never reach std::terminate
// via an uncaught-exception-in-thread-function).
inline void parallel_for(uint64_t n, int threads, const std::function<void(uint64_t, uint64_t)>& fn) {
    if (threads <= 1 || n == 0) { fn(0, n); return; }
    uint64_t chunk = (n + (uint64_t)threads - 1) / (uint64_t)threads;
    std::vector<std::thread> workers;
    std::mutex err_mu;
    std::exception_ptr first_error;
    auto run = [&](uint64_t begin, uint64_t end) {
        try {
            fn(begin, end);
        } catch (...) {
            std::lock_guard<std::mutex> lk(err_mu);
            if (!first_error) first_error = std::current_exception();
        }
    };
    try {
        for (int t = 0; t < threads; ++t) {
            uint64_t begin = (uint64_t)t * chunk;
            if (begin >= n) break;
            uint64_t end = std::min(n, begin + chunk);
            workers.emplace_back(run, begin, end);
        }
    } catch (...) {
        // emplace_back (or the std::thread constructor) threw after some
        // workers were already started: join everything before propagating,
        // so no still-joinable std::thread is destroyed (which would call
        // std::terminate).
        for (auto& w : workers) if (w.joinable()) w.join();
        throw;
    }
    for (auto& w : workers) w.join();
    if (first_error) std::rethrow_exception(first_error);
}

}  // namespace hm
