#include "generator/generator.h"
#include "generator/eval.h"
#include "chess/board.h"
#include <filesystem>

namespace hm {

SliceGen::SliceGen(const Material& m, const GenOptions& opt)
    : mat_(m), opt_(opt), idx_(m), ps_(idx_.size()) {
    for (int s = 0; s < 2; ++s) { dtm_[s].assign(ps_, DTM_UNSET); cnt_[s].assign(ps_, 0); }
}

void SliceGen::init_pass() {
    std::vector<PlacedPiece> pp; Board b;
    for (uint64_t c = 0; c < ps_; ++c) {
        if (!idx_.decode(c, pp)) { dtm_[0][c] = dtm_[1][c] = DTM_INVALID; continue; }
        auto e = idx_.encode(pp);
        if (!e || *e != c)       { dtm_[0][c] = dtm_[1][c] = DTM_INVALID; continue; }  // non-canonical duplicate
        for (int s = 0; s < 2; ++s) {
            b.reset(pp, (Color)s);
            if (b.opponent_in_check()) { dtm_[s][c] = DTM_INVALID; continue; }
            if (s == 1 && b.state() == PosState::Checkmate) dtm_[1][c] = 0;
        }
    }
}

void SliceGen::count_sweep() {}                        // Task 12 implements this

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
        return { dtm_[s][*e], cnt_[s][*e] };
    }
    return subs_.lookup(m, pp, b.stm());
}

bool SliceGen::scan_pass(int d) {
    Color mover = (d % 2) ? Color::White : Color::Black;
    int s = (int)mover;
    bool any = false;
    std::vector<PlacedPiece> pp; Board b;
    for (uint64_t c = 0; c < ps_; ++c) {
        if (dtm_[s][c] != DTM_UNSET) continue;
        idx_.decode(c, pp);                            // UNSET cells always decode
        b.reset(pp, mover);
        for (const Move& m : b.legal_moves()) {
            b.make(m);
            ValuePair v = eval_board(b, [this](Board& x) { return lookup_epless(x); });
            b.unmake(m);
            if (v.dtm == d - 1) { dtm_[s][c] = (uint8_t)d; any = true; break; }
        }
    }
    return any;
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

void SliceGen::finalize_and_write() {
    for (int s = 0; s < 2; ++s)
        for (uint64_t c = 0; c < ps_; ++c)
            if (dtm_[s][c] == DTM_UNSET) dtm_[s][c] = DTM_UNSOLVABLE;
    std::string meta = "{}";                           // extended in Task 13
    std::filesystem::create_directories(opt_.tables_dir);
    TableWriter::write(opt_.tables_dir + "/" + mat_.name() + ".hm", mat_, ps_,
                       max_dtm_ < 0 ? DTM_UNSOLVABLE : (uint8_t)max_dtm_, meta,
                       dtm_[0].data(), dtm_[1].data(), cnt_[0].data(), cnt_[1].data());
}

std::vector<std::string> generate(const Material& root, const GenOptions& opt) {
    std::vector<std::string> written;
    for (auto& m : Material::closure_topo(root)) {
        std::string path = opt.tables_dir + "/" + m.name() + ".hm";
        if (std::filesystem::exists(path)) continue;
        SliceGen g(m, opt);
        g.run_all_passes();
        g.count_sweep();                               // no-op until Task 12 implements it
        g.finalize_and_write();
        written.push_back(path);
    }
    return written;
}

}  // namespace hm
