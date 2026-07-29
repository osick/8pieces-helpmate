#include "generator/generator.h"
#include "generator/eval.h"
#include "generator/parallel.h"
#include "chess/board.h"
#include <atomic>
#include <filesystem>
#include <fstream>
#include <map>

namespace hm {

std::string describe_position(const std::vector<PlacedPiece>& pp, Color stm) {
    try { return Board::from_pieces(pp, stm).fen(); } catch (...) { return "<unavailable>"; }
}

namespace {
// Names the cell a failed lookup came from. Built only on the throwing path.
std::string cell_context(const Material& mat, uint64_t cell, int stm, int depth) {
    return "slice " + mat.name() + ", cell " + std::to_string(cell) +
           ", stm " + (stm ? "black" : "white") + ", scan depth " + std::to_string(depth);
}
}  // namespace

SliceGen::SliceGen(const Material& m, const GenOptions& opt)
    : mat_(m), opt_(opt), idx_(m), ps_(idx_.size()) {
    for (int s = 0; s < 2; ++s) { dtm_[s].assign(ps_, DTM_UNSET); cnt_[s].assign(ps_, 0); }
}

void SliceGen::init_pass() {
    // Each cell c is examined and written independently of every other cell
    // (opponent_in_check()/state() depend only on pp/s decoded from c itself),
    // so a disjoint [begin,end) range per worker is race-free; each worker
    // gets its own Board/pp (Board is stateful, not shareable across threads).
    parallel_for(ps_, opt_.threads, [this](uint64_t begin, uint64_t end) {
        std::vector<PlacedPiece> pp; Board b;
        for (uint64_t c = begin; c < end; ++c) {
            if (!idx_.decode(c, pp)) { dtm_[0][c] = dtm_[1][c] = DTM_INVALID; continue; }
            auto e = idx_.encode(pp);
            if (!e || *e != c)       { dtm_[0][c] = dtm_[1][c] = DTM_INVALID; continue; }  // non-canonical duplicate
            for (int s = 0; s < 2; ++s) {
                b.reset(pp, (Color)s);
                if (b.opponent_in_check()) { dtm_[s][c] = DTM_INVALID; continue; }
                if (s == 1 && b.state() == PosState::Checkmate) dtm_[1][c] = 0;
            }
        }
    });
}

void SliceGen::count_sweep() {
    // Pass d reads only counts of cells with dtm d-1, which the previous
    // iteration finalized; sub-slice tables were fully counted before this
    // slice (topological build order); eval_board merges EP branches with
    // the same min/sum rule. Within one d, cell c only ever writes cnt_[s][c]
    // and reads already-finalized lower-depth cells/sub-tables, so cells are
    // independent of each other and safe to split across worker threads;
    // the d loop itself stays sequential since depth d depends on depth d-1.
    parallel_for(ps_, opt_.threads, [this](uint64_t begin, uint64_t end) {
        for (uint64_t c = begin; c < end; ++c) if (dtm_[1][c] == 0) cnt_[1][c] = 1;
    });
    for (int d = 1; d <= max_dtm_; ++d) {
        int s = (d % 2) ? 0 : 1;
        parallel_for(ps_, opt_.threads, [this, s, d](uint64_t begin, uint64_t end) {
            std::vector<PlacedPiece> pp; Board b;
            for (uint64_t c = begin; c < end; ++c) {
                if (dtm_[s][c] != d) continue;
                if (!idx_.decode(c, pp))
                    throw GeneratorLookupError(cell_context(mat_, c, s, d) + ": solved cell does not decode");
                b.reset(pp, (Color)s);
                unsigned total = 0;
                try {
                    for (const Move& m : b.legal_moves()) {
                        b.make(m);
                        ValuePair v = eval_board(b, [this](Board& x) { return lookup_epless(x); });
                        b.unmake(m);
                        if (v.dtm == d - 1) total = std::min(255u, total + (unsigned)v.count);
                    }
                } catch (const GeneratorLookupError& e) {
                    throw GeneratorLookupError(cell_context(mat_, c, s, d) + ": " + e.what());
                }
                cnt_[s][c] = (uint8_t)total;              // >= 1 by construction of dtm
            }
        });
    }
}

const std::vector<uint8_t>& SliceGen::dtm(Color stm) const { return dtm_[(int)stm]; }
const std::vector<uint8_t>& SliceGen::cnt(Color stm) const { return cnt_[(int)stm]; }
const SliceIndex& SliceGen::index() const { return idx_; }
int SliceGen::max_dtm() const { return max_dtm_; }

ValuePair SliceGen::lookup_epless(Board& b) {
    auto pp = b.pieces();
    Material m = Material::of(pp);
    if (m == mat_) {
        auto e = idx_.encode(pp);
        int s = (int)b.stm();
        // encode() is disengaged for positions this slice cannot hold (kings adjacent/equal).
        // Dereferencing it unchecked read uninitialised stack, and since vec[i] is
        // *(data() + i) with wrapping arithmetic, a garbage index lands anywhere in the
        // address space -- a silently wrong value at best, a wild access at worst.
        if (!e)
            throw GeneratorLookupError("position not encodable in own slice " + m.name() +
                                       "; position " + describe_position(pp, b.stm()));
        if (*e >= ps_)
            throw GeneratorLookupError("cell " + std::to_string(*e) + " out of range for slice " +
                                       m.name() + " (plane size " + std::to_string(ps_) +
                                       "); position " + describe_position(pp, b.stm()));
        return { dtm_[s][*e], cnt_[s][*e] };
    }
    return subs_.lookup(m, pp, b.stm());
}

bool SliceGen::scan_pass(int d) {
    // Safety argument for running this pass's cell loop across worker threads:
    // pass d writes only the value d, and only into currently-UNSET cells of
    // ONE plane (dtm_[s], s = mover's side); it reads (a) the opposite-parity
    // plane, which this pass never writes -- a cell's successors after one
    // ply always have the other side to move -- (b) finished sub-tables
    // (read-only after load_for(), before any pass runs), and (c) same-plane
    // values only to check DTM_UNSET (never written by another cell). So two
    // workers touching different cells c1 != c2 never read-during-write or
    // write-during-write each other's data. Each worker owns a disjoint cell
    // range (and its own Board/pp, since Board is stateful); the only shared
    // mutable state is `any`, updated through a std::atomic<bool>.
    Color mover = (d % 2) ? Color::White : Color::Black;
    int s = (int)mover;
    std::atomic<bool> any{false};
    parallel_for(ps_, opt_.threads, [this, s, mover, d, &any](uint64_t begin, uint64_t end) {
        std::vector<PlacedPiece> pp; Board b;
        for (uint64_t c = begin; c < end; ++c) {
            if (dtm_[s][c] != DTM_UNSET) continue;
            if (!idx_.decode(c, pp))                       // UNSET cells always decode
                throw GeneratorLookupError(cell_context(mat_, c, s, d) + ": UNSET cell does not decode");
            b.reset(pp, mover);
            // Catch here rather than tracking the current cell in a variable: zero-cost EH puts
            // nothing on the happy path, so the hot loop keeps the instruction sequence it had.
            try {
                for (const Move& m : b.legal_moves()) {
                    b.make(m);
                    ValuePair v = eval_board(b, [this](Board& x) { return lookup_epless(x); });
                    b.unmake(m);
                    if (v.dtm == d - 1) { dtm_[s][c] = (uint8_t)d; any = true; break; }
                }
            } catch (const GeneratorLookupError& e) {
                throw GeneratorLookupError(cell_context(mat_, c, s, d) + ": " + e.what());
            }
        }
    });
    return any.load();
}

void SliceGen::run_all_passes() {
    subs_.load_for(mat_, opt_.tables_dir);
    init_pass();
    max_dtm_ = -1;
    { bool any0 = false; for (uint64_t c = 0; c < ps_; ++c) if (dtm_[1][c] == 0) { any0 = true; break; }
      if (any0) max_dtm_ = 0; }
    int misses = 0;
    for (int d = 1; d <= DTM_MAX && misses < 2; ++d) {
        if (scan_pass(d)) { max_dtm_ = d; misses = 0; } else misses++;
    }
}

nlohmann::json SliceGen::stats_json() const {
    using nlohmann::json;
    static const char* kStm[2] = {"wtm", "btm"};

    json cells_invalid, cells_unsolvable, histogram, uniqueness;
    for (int s = 0; s < 2; ++s) {
        uint64_t invalid = 0, unsolvable = 0;
        std::map<int, uint64_t> hist;
        std::map<int, std::map<int, uint64_t>> uniq;
        for (uint64_t c = 0; c < ps_; ++c) {
            uint8_t d = dtm_[s][c];
            if (d == DTM_INVALID) { ++invalid; continue; }
            if (d == DTM_UNSOLVABLE) { ++unsolvable; continue; }
            ++hist[d];
            ++uniq[d][cnt_[s][c]];
        }
        cells_invalid[kStm[s]] = invalid;
        cells_unsolvable[kStm[s]] = unsolvable;

        json hj = json::object();
        for (auto& [depth, count] : hist) hj[std::to_string(depth)] = count;
        histogram[kStm[s]] = hj;

        json uj = json::object();
        for (auto& [depth, counts] : uniq) {
            json cj = json::object();
            for (auto& [cnt, n] : counts) cj[std::to_string(cnt)] = n;
            uj[std::to_string(depth)] = cj;
        }
        uniqueness[kStm[s]] = uj;
    }

    json deepest = json::array(), deepest_unique = json::array();
    if (max_dtm_ >= 0) {
        std::vector<PlacedPiece> pp;
        int s = (max_dtm_ % 2) ? 0 : 1;                 // parity: odd depths are wtm, even are btm
        for (uint64_t c = 0; c < ps_ && deepest.size() < 5; ++c) {
            if (dtm_[s][c] != (uint8_t)max_dtm_) continue;
            idx_.decode(c, pp);
            deepest.push_back(Board::from_pieces(pp, (Color)s).fen());
        }
        for (int d = max_dtm_; d >= 0 && deepest_unique.empty(); --d) {
            int ss = (d % 2) ? 0 : 1;
            for (uint64_t c = 0; c < ps_ && deepest_unique.size() < 5; ++c) {
                if (dtm_[ss][c] != (uint8_t)d || cnt_[ss][c] != 1) continue;
                idx_.decode(c, pp);
                deepest_unique.push_back(Board::from_pieces(pp, (Color)ss).fen());
            }
        }
    }

    json j;
    j["material"] = mat_.name();
    j["plane_size"] = ps_;
    j["max_dtm"] = max_dtm_ < 0 ? (int)DTM_UNSOLVABLE : max_dtm_;
    j["cells"] = {{"invalid", cells_invalid}, {"unsolvable", cells_unsolvable}};
    j["dtm_histogram"] = histogram;
    j["uniqueness"] = uniqueness;
    j["deepest"] = deepest;
    j["deepest_unique"] = deepest_unique;
    j["generator_version"] = "0.1.0";
    return j;
}

void SliceGen::finalize_and_write() {
    for (int s = 0; s < 2; ++s)
        for (uint64_t c = 0; c < ps_; ++c)
            if (dtm_[s][c] == DTM_UNSET) dtm_[s][c] = DTM_UNSOLVABLE;
    nlohmann::json j = stats_json();
    std::string meta = j.dump(2);
    std::filesystem::create_directories(opt_.tables_dir);
    std::string base = opt_.tables_dir + "/" + mat_.name();
    TableWriter::write(base + ".hm", mat_, ps_,
                       max_dtm_ < 0 ? DTM_UNSOLVABLE : (uint8_t)max_dtm_, meta,
                       dtm_[0].data(), dtm_[1].data(), cnt_[0].data(), cnt_[1].data());
    std::ofstream out(base + ".stats.json", std::ios::trunc);
    out << meta;
}

std::vector<std::string> generate(const Material& root, const GenOptions& opt) {
    std::vector<std::string> written;
    for (auto& m : Material::closure_topo(root)) {
        std::string path = opt.tables_dir + "/" + m.name() + ".hm";
        if (std::filesystem::exists(path)) continue;
        SliceGen g(m, opt);
        g.run_all_passes();
        g.count_sweep();
        g.finalize_and_write();
        written.push_back(path);
    }
    return written;
}

}  // namespace hm
