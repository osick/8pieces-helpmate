#pragma once
#include "chess/types.h"
#include "indexing/material.h"
#include "indexing/slice_index.h"
#include <cstdint>
#include <string>
#include <vector>

namespace hm {

struct GenOptions { std::string tables_dir = "tables"; int threads = 1; };

// Builds the whole closure (missing slices only), root last. Returns paths of written files.
std::vector<std::string> generate(const Material& root, const GenOptions& = {});

class SliceGen {                                      // exposed for tests
public:
    SliceGen(const Material&, const GenOptions&);
    void init_pass();
    bool scan_pass(int d);                            // Task 10
    void run_all_passes();                            // Task 10: scan until fixed point; sets max_dtm_
    void count_sweep();                               // Task 12
    void finalize_and_write();                        // Task 10 (stats extended in Task 13)
    // test accessors:
    const std::vector<uint8_t>& dtm(Color stm) const;
    const std::vector<uint8_t>& cnt(Color stm) const;
    const SliceIndex& index() const;
    int max_dtm() const;

private:
    Material mat_;
    GenOptions opt_;
    SliceIndex idx_;
    uint64_t ps_;
    std::vector<uint8_t> dtm_[2];
    std::vector<uint8_t> cnt_[2];
    int max_dtm_ = 0;
};

}  // namespace hm
