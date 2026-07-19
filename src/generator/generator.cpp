#include "generator/generator.h"
#include "chess/board.h"

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

const std::vector<uint8_t>& SliceGen::dtm(Color stm) const { return dtm_[(int)stm]; }
const std::vector<uint8_t>& SliceGen::cnt(Color stm) const { return cnt_[(int)stm]; }
const SliceIndex& SliceGen::index() const { return idx_; }
int SliceGen::max_dtm() const { return max_dtm_; }

}  // namespace hm
