#pragma once
#include "chess/board.h"
#include "chess/types.h"
#include "format/table_file.h"
#include "indexing/material.h"
#include "indexing/slice_index.h"
#include <functional>
#include <map>
#include <memory>
#include <mutex>
#include <optional>
#include <stdexcept>
#include <string>
#include <vector>

namespace hm {

struct MissingTableError : std::runtime_error { using std::runtime_error::runtime_error; };

// Selection criteria for Tablebase::mine. -1 means "don't filter on this".
// Grouped in a struct so later filters (the web dashboard will want more) can
// be added without changing every call site again.
struct MineFilter {
    int dtm    = -1;   // required, exact
    int count  = -1;   // optional, exact
    int starts = -1;   // optional, exact: distinct first moves across optimal lines
    int ends   = -1;   // optional, exact: distinct final (mating) moves
};

// Read side of the tablebase: loads generated .hm files on demand (lazily, cached)
// and answers position queries. All public methods are logically const (internal
// cache access is mutex-guarded), so a single Tablebase can be shared/queried
// concurrently from multiple threads.
class Tablebase {
public:
    explicit Tablebase(std::string dir);

    struct Probe { int dtm; int count; bool flipped; };  // flipped: colors were swapped to match a slice

    // nullopt = position is valid but unsolvable. Throws MissingTableError (with the
    // slice names tried) or std::invalid_argument (bad FEN / castling rights).
    std::optional<Probe> probe(const std::string& fen) const;
    // one optimal line, SAN, from `fen` to mate.
    std::vector<std::string> line(const std::string& fen) const;
    // all optimal lines, SAN, capped at `max`.
    std::vector<std::vector<std::string>> lines(const std::string& fen, int max = 100) const;
    // stream FENs of canonical cells of material `m` matching `f`; stop as soon as
    // `cb` returns false.
    void mine(const Material& m, const MineFilter& f,
              const std::function<bool(const std::string&)>& cb) const;
    // sidecar stats content for material `m`; throws MissingTableError if absent.
    std::string stats_json(const Material& m) const;
    // "h#2", "h#1.5", "h#0" style helpmate notation for a dtm/side-to-move pair.
    static std::string h_notation(int dtm, Color stm);

private:
    struct Slice { TableReader reader; SliceIndex index; };
    const Slice* load(const Material& m) const;
    ValuePair value_of(Board& b) const;
    void collect_lines(Board& b, std::vector<std::string>& path,
                        std::vector<std::vector<std::string>>& out, int max) const;

    std::string dir_;
    mutable std::mutex mu_;
    mutable std::map<std::string, std::unique_ptr<Slice>> cache_;
};

}  // namespace hm
