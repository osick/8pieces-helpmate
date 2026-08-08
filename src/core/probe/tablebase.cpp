#include "probe/tablebase.h"

#include <set>
#include <utility>

#include "chess/san.h"
#include "generator/eval.h"
#include "themes/registry.h"

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
    std::string path = dir_ + "/" + m.name() + ".hm";
    TableReader::OpenError oerr = TableReader::OpenError::None;
    auto r = TableReader::open(path, &oerr);
    if (!r && oerr == TableReader::OpenError::UnsupportedVersion)
        throw UnsupportedTableVersionError("table " + path + " was written by a newer helpmate"
                                           " (unsupported table format version); upgrade this build");
    if (r) {
        // Identity check (before caching anything): the file must actually be the table
        // its name promises, or every later lookup would silently index the wrong planes.
        SliceIndex si(m);
        if (r->material_name() != m.name())
            throw std::runtime_error("table " + path + " is for material '" +
                                     r->material_name() + "', expected '" + m.name() + "'");
        if (r->plane_size() != si.size())
            throw std::runtime_error("table " + path + " has plane size " +
                                     std::to_string(r->plane_size()) + ", expected " +
                                     std::to_string(si.size()) + " for " + m.name());
        auto& slot = cache_[m.name()];
        slot = std::make_unique<Slice>(Slice{std::move(*r), std::move(si)});
        return slot.get();
    }
    return cache_[m.name()].get();  // caches the miss
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
    const Slice* s = nullptr;
    // A future-format primary table must not preempt the color-flip fallback: remember
    // the diagnostic and keep going. Only the primary attempt is wrapped -- if the flip
    // attempt itself throws (its own table is unreadable/future-format), that propagates
    // unmodified, and if it merely comes up empty, the remembered primary error (if any)
    // is more informative than a generic "no table" message.
    std::optional<UnsupportedTableVersionError> primary_err;
    try {
        s = load(m);
    } catch (const UnsupportedTableVersionError& e) {
        primary_err = e;
    }
    if (!s) {
        target = flip_colors(*b);
        flipped = true;
        if (!load(Material::of(target.pieces()))) {
            if (primary_err) throw *primary_err;
            throw MissingTableError("no table for " + m.name() + " nor its color flip");
        }
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

void Tablebase::collect_solutions(Board& b, std::vector<Ply>& path, std::vector<Solution>& out,
                                  const Board& start, int max) const {
    if ((int)out.size() >= max) return;
    ValuePair v = value_of(b);
    if (v.dtm == 0) {
        out.push_back(Solution{start, path});
        return;
    }
    for (const Move& m : b.legal_moves()) {
        if ((int)out.size() >= max) return;
        b.make(m);
        ValuePair nv = value_of(b);
        bool on_optimal = nv.dtm <= DTM_MAX && (int)nv.dtm == (int)v.dtm - 1;
        b.unmake(m);
        if (!on_optimal) continue;

        Ply p;
        p.from = m.from;
        p.to = m.to;
        p.promotion = m.promotion();
        p.is_ep = m.is_ep();
        for (const auto& pp : b.pieces()) {  // b is still PRE-move here
            if (pp.square == m.from) p.piece = pp.piece;
            else if (pp.square == m.to) p.captured = pp.piece.type;
        }
        // An en-passant capture takes a pawn that is NOT on m.to, so the scan
        // above cannot see it.
        if (p.is_ep) p.captured = PieceType::Pawn;

        b.make(m);
        p.is_check = b.in_check();
        p.after = b;
        path.push_back(std::move(p));
        collect_solutions(b, path, out, start, max);
        path.pop_back();
        b.unmake(m);
    }
}

std::vector<Solution> Tablebase::solutions(const std::string& fen, int max) const {
    auto b = Board::from_fen(fen);
    if (!b) throw std::invalid_argument("bad FEN (or castling rights): " + fen);
    Board start = *b;
    std::vector<Solution> out;
    std::vector<Ply> path;
    collect_solutions(*b, path, out, start, max);
    return out;
}

std::vector<std::string> Tablebase::line(const std::string& fen) const {
    auto ls = lines(fen, 1);
    return ls.empty() ? std::vector<std::string>{} : ls[0];
}

std::vector<MoveInfo> Tablebase::moves(const std::string& fen) const {
    auto b = Board::from_fen(fen);
    if (!b) throw std::invalid_argument("bad FEN: " + fen);
    int parent_dtm = -1;
    if (auto p = probe(fen)) parent_dtm = p->dtm;

    std::vector<MoveInfo> out;
    for (const Move& m : b->legal_moves()) {
        MoveInfo mi;
        mi.uci = m.uci();
        mi.san = san(*b, m);          // SAN must be computed BEFORE the move is made
        b->make(m);
        mi.fen = b->fen();
        b->unmake(m);
        try {
            if (auto c = probe(mi.fen)) {
                mi.dtm = c->dtm;
                mi.count = c->count;
                mi.solvable = true;
                // parent_dtm > 0: a dtm-0 position is mate and has no legal moves, so the
                // loop body never runs for it (this guard just avoids an accidental match
                // against the sentinel -1 when the parent itself was unsolvable).
                mi.optimal = parent_dtm > 0 && c->dtm == parent_dtm - 1;
            }
        } catch (const MissingTableError&) {
            // no table for the resulting material: leave solvable=false
        } catch (const std::invalid_argument&) {
            // The move leads somewhere the tablebase cannot describe at all --
            // in practice a king capture, which is only reachable when the
            // query position is itself illegal (the side not to move is
            // already in check). The position editor produces such positions
            // on the way to real ones, so the move list must stay complete and
            // report the move as having no value, exactly like a missing
            // table. Throwing here would answer a whole legal-move request
            // with an invalid_fen error naming a FEN the caller never sent.
        }
        out.push_back(std::move(mi));
    }
    return out;
}

SolutionShape shape_of(int count, const std::vector<std::vector<std::string>>& lines) {
    if (count >= (int)COUNT_SAT) return {0, 0, false};  // cannot enumerate exhaustively
    std::set<std::string> firsts, lasts;
    for (const auto& l : lines) {
        if (l.empty()) continue;                       // dtm 0: already mate, no moves
        firsts.insert(l.front());
        lasts.insert(l.back());
    }
    return {(int)firsts.size(), (int)lasts.size(), true};
}

SolutionShape Tablebase::solution_shape(const std::string& fen) const {
    auto p = probe(fen);
    if (!p) return {0, 0, true};                       // unsolvable: no solutions at all
    if (p->count >= (int)COUNT_SAT) return shape_of(p->count, {});  // never enumerate a saturated position
    return shape_of(p->count, lines(fen, p->count));
}

void Tablebase::mine(const Material& m, const MineFilter& f,
                      const std::function<bool(const std::string&)>& cb,
                      uint64_t* skipped_saturated) const {
    const Slice* s = load(m);
    if (!s) throw MissingTableError("no table for " + m.name());
    Color stm = (f.dtm % 2) ? Color::White : Color::Black;  // parity invariant: wtm dtm odd, btm dtm even

    // Resolve theme names ONCE, before the scan: a typo must be an error that
    // names the valid options, not millions of positions filtered by nothing.
    std::vector<themes::Detector> dets;
    for (const auto& n : f.themes) {
        const auto* d = themes::find_theme(n);
        if (!d) throw std::invalid_argument("unknown theme: \"" + n + "\"");
        dets.push_back(d->fn);
    }

    const bool want_shape = f.starts >= 0 || f.ends >= 0;
    const bool want_solutions = want_shape || !dets.empty();
    std::vector<PlacedPiece> pp;
    // Read the two planes in block-sized chunks instead of one cell at a time.
    // get() on a compressed table takes the block cache's mutex and memcpys a
    // single byte per call; over a whole plane that -- not the decompression --
    // was the cost, measured at 14x raw on KRvkbn before this loop was chunked.
    // read_values() pays one lock and one memcpy per block touched.
    constexpr size_t kScanChunk = 1 << 16;
    const uint64_t plane_cells = s->index.size();
    std::vector<uint8_t> dtm_buf(kScanChunk), cnt_buf(kScanChunk);
    uint64_t chunk_base = 0;
    size_t chunk_n = 0;
    for (uint64_t c = 0; c < plane_cells; ++c) {
        if (c - chunk_base >= chunk_n) {
            chunk_base = c;
            chunk_n = (size_t)std::min<uint64_t>(kScanChunk, plane_cells - c);
            s->reader.read_values(stm, chunk_base, chunk_n, dtm_buf.data(), cnt_buf.data());
        }
        ValuePair v{dtm_buf[c - chunk_base], cnt_buf[c - chunk_base]};
        if (v.dtm != (uint8_t)f.dtm) continue;
        if (f.count >= 0 && v.count != (uint8_t)f.count) continue;
        if (!s->index.decode(c, pp)) continue;
        Board b = Board::from_pieces(pp, stm);
        std::string fen = b.fen();
        if (want_solutions) {
            // v.count is this cell's own stored count -- the same number a
            // probe() of `fen` would return. Using it directly saves a
            // redundant table lookup per candidate; two things make that
            // safe, not "probe() cannot color-flip" (it can, in general):
            // Board::from_pieces(pp, stm) above defaults ep_square to -1, so
            // eval_board's EP branch -- the only place probe()'s answer can
            // differ from this cell's raw value -- is inert for every FEN
            // built here; and load(m) already succeeded (this loop is
            // iterating `s`, a slice it returned), so probe()'s color-flip
            // fallback, which only triggers when the PRIMARY load fails,
            // never runs for `fen`. Mining pawn material with reconstructed
            // en-passant positions is a plausible next rung -- if that ever
            // makes fen carry a real ep_square, the first load-bearer above
            // stops holding and this shortcut needs revisiting.
            if (v.count >= COUNT_SAT) {  // unknowable, never guessed at
                if (skipped_saturated) ++*skipped_saturated;
                continue;
            }
            if (want_shape) {
                // --starts/--ends are a released v0.6.2 feature (see CHANGELOG.md)
                // keyed on SAN, not on (from, to, promotion): SAN disambiguates a
                // capture from a quiet move sharing the same (from, to) (Qxa4# vs
                // Qa4#: v0.6.2 counts 2 distinct mating moves), and distinguishes
                // two moves that happen to share a destination square but render
                // identically otherwise (Qb4-b1# vs Qe4-b1#, both SAN "Qb1#": v0.6.2
                // counts 1). A (from, to, promotion) key gets both cases backwards.
                // Changing --ends's meaning as a side effect of adding themes is not
                // acceptable, so this goes through lines()/shape_of exactly like
                // v0.6.2 did, not through solutions().
                SolutionShape sh = shape_of((int)v.count, lines(fen, (int)v.count));
                if (f.starts >= 0 && sh.starts != f.starts) continue;
                if (f.ends >= 0 && sh.ends != f.ends) continue;
            }
            if (!dets.empty()) {
                auto sols = solutions(fen, (int)v.count);
                themes::ThemeInput in{b, std::nullopt, sols};
                bool all_present = true;
                for (auto d : dets) {  // AND across themes; `any` within one is now
                    if (!d(in)) {      // inside d itself (any_of<>)
                        all_present = false;
                        break;
                    }
                }
                if (!all_present) continue;
            }
        }
        if (!cb(fen)) return;
    }
}

std::vector<std::string> Tablebase::themes_of(const std::string& fen, int max) const {
    auto b = Board::from_fen(fen);
    if (!b) throw std::invalid_argument("bad FEN (or castling rights): " + fen);
    std::vector<Solution> sols = solutions(fen, max);
    themes::ThemeInput in{*b, std::nullopt, sols};
    return themes::detect(in);
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
