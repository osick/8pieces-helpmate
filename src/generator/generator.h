#pragma once
#include "chess/board.h"
#include "chess/types.h"
#include "format/table_file.h"
#include "indexing/material.h"
#include "indexing/slice_index.h"
#include <nlohmann/json.hpp>
#include <cstdint>
#include <map>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace hm {

// A generator lookup hit a position its tables cannot answer. Every throw site attaches the
// material, the FEN of the offending position and (once it has unwound to the cell loop) the
// slice/cell/depth it came from. Before this existed the same conditions surfaced either as a
// bare std::out_of_range("map::at") with no context, or -- worse -- as `*e` on a disengaged
// optional, i.e. UB: a garbage index into a 121 MB plane, which only shows up much later as a
// SIGSEGV somewhere unrelated (typically inside malloc).
struct GeneratorLookupError : std::runtime_error { using std::runtime_error::runtime_error; };

// FEN of a decoded piece list, for error messages ("<unavailable>" if it cannot be rendered).
std::string describe_position(const std::vector<PlacedPiece>& pp, Color stm);

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
    // Each step is checked rather than assumed: only direct successors of the slice being
    // generated are loaded, and encode() is disengaged for positions no slice can hold (e.g.
    // adjacent kings), so an unexpected post-move position must fail loudly and locally.
    ValuePair lookup(const Material& m, const std::vector<PlacedPiece>& pp, Color stm) const {
        auto it = t_.find(m.name());
        if (it == t_.end())
            throw GeneratorLookupError("no sub-table loaded for material " + m.name() +
                                       " (only direct successors are loaded); position " +
                                       describe_position(pp, stm));
        auto& [rd, si] = it->second;
        auto e = si.encode(pp);
        if (!e)
            throw GeneratorLookupError("position not encodable in sub-table " + m.name() +
                                       "; position " + describe_position(pp, stm));
        if (*e >= rd.plane_size())
            throw GeneratorLookupError("cell " + std::to_string(*e) + " out of range for sub-table " +
                                       m.name() + " (plane size " + std::to_string(rd.plane_size()) +
                                       "); position " + describe_position(pp, stm));
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
    nlohmann::json stats_json() const;                // Task 13
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
