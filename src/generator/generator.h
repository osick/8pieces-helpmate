#pragma once
#include "chess/board.h"
#include "chess/types.h"
#include "format/table_file.h"
#include "indexing/material.h"
#include "indexing/slice_index.h"
#include <cstdint>
#include <map>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace hm {

struct GenOptions { std::string tables_dir = "tables"; int threads = 1; };

// Builds the whole closure (missing slices only), root last. Returns paths of written files.
std::vector<std::string> generate(const Material& root, const GenOptions& = {});

// Finished successor-slice tables, loaded on demand for cross-slice lookups
// (after a capture / promotion changes the material of a position).
struct SubTables {
    std::map<std::string, std::pair<TableReader, SliceIndex>> t_;
    void load_for(const Material& m, const std::string& dir) {
        for (auto& s : m.successors()) {
            if (t_.count(s.name())) continue;
            auto r = TableReader::open(dir + "/" + s.name() + ".hm");
            if (!r) throw std::runtime_error("missing sub-table " + s.name());
            t_.emplace(s.name(), std::pair(std::move(*r), SliceIndex(s)));
        }
    }
    ValuePair lookup(const Material& m, const std::vector<PlacedPiece>& pp, Color stm) const {
        auto& [rd, si] = t_.at(m.name());
        auto e = si.encode(pp);                        // legal position => always encodable
        return rd.get(stm, *e);
    }
};

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
    ValuePair lookup_epless(Board& b);                 // Task 10: routes to own table or a sub-table

    Material mat_;
    GenOptions opt_;
    SliceIndex idx_;
    uint64_t ps_;
    std::vector<uint8_t> dtm_[2];
    std::vector<uint8_t> cnt_[2];
    int max_dtm_ = 0;
    SubTables subs_;
};

}  // namespace hm
