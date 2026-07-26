#include "probe/tablebase.h"
#include "chess/san.h"
#include "generator/eval.h"
#include <utility>

namespace hm {

namespace {
// Color flip is exact here because castling rights don't exist in this game:
// mirror ranks (sq ^ 56), swap every piece's color, flip the side to move, and
// mirror any en passant square the same way.
Board flip_colors(const Board& b) {
    std::vector<PlacedPiece> pp;
    for (auto& p : b.pieces())
        pp.push_back({{p.piece.color == Color::White ? Color::Black : Color::White, p.piece.type},
                       (uint8_t)(p.square ^ 56)});
    Color stm = b.stm() == Color::White ? Color::Black : Color::White;
    int ep = b.ep_square();
    return Board::from_pieces(pp, stm, ep >= 0 ? (ep ^ 56) : -1);
}
}  // namespace

Tablebase::Tablebase(std::string dir) : dir_(std::move(dir)) {}

const Tablebase::Slice* Tablebase::load(const Material& m) const {
    std::lock_guard lk(mu_);
    auto it = cache_.find(m.name());
    if (it != cache_.end()) return it->second.get();
    auto r = TableReader::open(dir_ + "/" + m.name() + ".hm");
    auto& slot = cache_[m.name()];
    if (r) slot = std::make_unique<Slice>(Slice{std::move(*r), SliceIndex(m)});
    return slot.get();
}

ValuePair Tablebase::value_of(Board& b) const {
    auto lookup = [this](Board& x) -> ValuePair {
        Material m = Material::of(x.pieces());
        const Slice* s = load(m);
        if (!s) throw MissingTableError("no table for " + m.name());
        auto cell = s->index.encode(x.pieces());
        if (!cell) throw MissingTableError("position not encodable in table for " + m.name());
        return s->reader.get(x.stm(), *cell);
    };
    return eval_board(b, lookup);
}

std::optional<Tablebase::Probe> Tablebase::probe(const std::string& fen) const {
    auto b = Board::from_fen(fen);
    if (!b) throw std::invalid_argument("bad FEN (or castling rights): " + fen);
    Material m = Material::of(b->pieces());
    bool flipped = false;
    Board target = *b;
    if (!load(m)) {
        target = flip_colors(*b);
        flipped = true;
        if (!load(Material::of(target.pieces())))
            throw MissingTableError("no table for " + m.name() + " nor its color flip");
    }
    ValuePair v = value_of(target);
    if (v.dtm > DTM_MAX) return std::nullopt;  // UNSOLVABLE (INVALID can't reach here: FEN was legal)
    return Probe{(int)v.dtm, (int)v.count, flipped};
}

void Tablebase::collect_lines(Board& b, std::vector<std::string>& path,
                               std::vector<std::vector<std::string>>& out, int max) const {
    if ((int)out.size() >= max) return;
    ValuePair v = value_of(b);
    if (v.dtm == 0) { out.push_back(path); return; }
    for (const Move& m : b.legal_moves()) {
        if ((int)out.size() >= max) return;
        b.make(m);
        ValuePair nv = value_of(b);
        bool on_optimal = nv.dtm <= DTM_MAX && (int)nv.dtm == (int)v.dtm - 1;
        b.unmake(m);
        if (!on_optimal) continue;
        path.push_back(san(b, m));  // b is still pre-move here; san() restores it too
        b.make(m);
        collect_lines(b, path, out, max);
        b.unmake(m);
        path.pop_back();
    }
}

std::vector<std::vector<std::string>> Tablebase::lines(const std::string& fen, int max) const {
    auto b = Board::from_fen(fen);
    if (!b) throw std::invalid_argument("bad FEN (or castling rights): " + fen);
    std::vector<std::vector<std::string>> out;
    std::vector<std::string> path;
    collect_lines(*b, path, out, max);
    return out;
}

std::vector<std::string> Tablebase::line(const std::string& fen) const {
    auto ls = lines(fen, 1);
    return ls.empty() ? std::vector<std::string>{} : ls[0];
}

void Tablebase::mine(const Material& m, int dtm, int count,
                      const std::function<bool(const std::string&)>& cb) const {
    const Slice* s = load(m);
    if (!s) throw MissingTableError("no table for " + m.name());
    Color stm = (dtm % 2) ? Color::White : Color::Black;  // parity invariant: wtm dtm odd, btm dtm even
    std::vector<PlacedPiece> pp;
    for (uint64_t c = 0; c < s->index.size(); ++c) {
        ValuePair v = s->reader.get(stm, c);
        if (v.dtm != (uint8_t)dtm) continue;
        if (count >= 0 && v.count != (uint8_t)count) continue;
        if (!s->index.decode(c, pp)) continue;
        if (!cb(Board::from_pieces(pp, stm).fen())) return;
    }
}

std::string Tablebase::stats_json(const Material& m) const {
    const Slice* s = load(m);
    if (!s) throw MissingTableError("no table for " + m.name());
    return s->reader.meta_json();
}

std::string Tablebase::h_notation(int dtm, Color) {
    int moves = dtm / 2;
    return "h#" + std::to_string(moves) + (dtm % 2 ? ".5" : "");
}

}  // namespace hm
