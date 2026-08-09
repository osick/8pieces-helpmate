#include "themes/line_themes.h"

#include <set>

#include "themes/attack.h"
#include "themes/trajectory.h"

namespace hm::themes {
namespace {

bool excelsior_for(const Solution& s, std::optional<Color> want) {
    const auto start_pieces = s.start.pieces();
    for (const auto& t : trajectories(s)) {
        if (!t.promoted) continue;
        if (want && t.color != *want) continue;
        const int home = (t.color == Color::White) ? 1 : 6;  // own second rank, 0-indexed
        const uint8_t origin = t.squares.front();
        if (sq_rank(origin) != home) continue;
        // Defensive: a trajectory that promotes can only be a pawn's, so this
        // scan cannot currently reject anything the rank test let through. It
        // states the theme's own definition rather than relying on that.
        for (const auto& p : start_pieces)
            if (p.square == origin && p.piece.color == t.color && p.piece.type == PieceType::Pawn)
                return true;
    }
    return false;
}

bool single_for(const Solution& s, Color c) {
    int n = 0;
    for (const auto& t : trajectories(s))
        if (t.color == c) ++n;
    return n == 1;
}

}  // namespace

bool has_promotion(const Solution& s) {
    for (const auto& p : s.plies)
        if (p.promotion) return true;
    return false;
}

bool has_underpromotion(const Solution& s) {
    for (const auto& p : s.plies)
        if (p.promotion && *p.promotion != PieceType::Queen) return true;
    return false;
}

bool has_excelsior(const Solution& s) { return excelsior_for(s, std::nullopt); }
bool has_excelsior_white(const Solution& s) { return excelsior_for(s, Color::White); }
bool has_excelsior_black(const Solution& s) { return excelsior_for(s, Color::Black); }

bool has_switchback(const Solution& s) {
    for (const auto& t : trajectories(s))
        for (size_t i = 0; i + 2 < t.squares.size(); ++i)
            if (t.squares[i] == t.squares[i + 2]) return true;
    return false;
}

bool has_closed_walk(const Solution& s) {
    for (const auto& t : trajectories(s))
        for (size_t i = 0; i < t.squares.size(); ++i)
            for (size_t j = i + 3; j < t.squares.size(); ++j) {
                if (t.squares[i] != t.squares[j]) continue;
                std::set<uint8_t> mid(t.squares.begin() + i + 1, t.squares.begin() + j);
                // A path that touches its own start square in between is a
                // sequence of switchbacks, not one circuit. The size test
                // restates the theme's two-square minimum; the j >= i + 3 gap
                // already implies it, since a ply always changes square.
                //
                // mid.size() alone only counts DISTINCT intermediate squares:
                // e1-e2-d2-e2-e1 has mid = {e2, d2}, size 2, yet retraces
                // through e2 twice rather than circulating -- a shuffle, not
                // a Rundlauf. Requiring mid.size() == j - i - 1 (every
                // intermediate ply lands on a square none of the others did)
                // rules that out while leaving a genuine circuit (no repeats
                // at all between i and j) unaffected.
                if (mid.size() == j - i - 1 && mid.count(t.squares[i]) == 0) return true;
            }
    return false;
}

bool has_self_block(const Solution& s) {
    const auto ps = final_board(s).pieces();
    int bk = -1;
    for (const auto& p : ps)
        if (p.piece.type == PieceType::King && p.piece.color == Color::Black) bk = p.square;
    if (bk < 0) return false;

    for (int f : king_field(bk)) {
        const PlacedPiece* occ = nullptr;
        for (const auto& p : ps)
            if ((int)p.square == f) occ = &p;
        // The colour and king tests are untestable by DELETION, not untested:
        // in a real mate a white unit standing on a field square is always
        // attacked, so the attackers_of check below already skips it whether
        // or not this line does, and no king is ever adjacent to itself. But
        // INVERTING either check is caught immediately by the self-block
        // positive fixture, whose blocking square g8 holds a black rook --
        // an inverted colour test would skip that rook, an inverted king
        // test would skip it too.
        if (!occ || occ->piece.color != Color::Black || occ->piece.type == PieceType::King) continue;
        // Same king-removed rule as is_pure: a blocked square that White also
        // attacks is not a self-block, it is double duty.
        if (attackers_of(ps, Color::White, f, Color::Black) != 0) continue;
        // The VERDICT is provably right, but not for the tempting reason. This
        // loop does not identify which ply put the occupant on f: black unit A
        // can arrive on f, leave again, and black unit B arrive later, in which
        // case the first match is A's ply, not B's. It is still a genuine
        // self-block, because B cannot be standing on f without a `to == f`
        // ply of its own -- a unit parked on f from the start would have
        // blocked every other black unit from ever moving there. So the answer
        // is correct; do not reuse this loop to report WHICH ply caused it.
        for (const auto& ply : s.plies)  // did a black unit MOVE there?
            if (ply.piece.color == Color::Black && (int)ply.to == f) return true;
    }
    return false;
}

bool is_single_piece_white(const Solution& s) { return single_for(s, Color::White); }
bool is_single_piece_black(const Solution& s) { return single_for(s, Color::Black); }
bool is_single_piece(const Solution& s) { return is_single_piece_white(s) || is_single_piece_black(s); }

bool has_en_passant(const Solution& s) {
    for (const auto& p : s.plies)
        if (p.is_ep) return true;
    return false;
}

bool has_kniest(const Solution& s) {
    const Board& fin = final_board(s);
    int bk = -1;
    for (const auto& pp : fin.pieces())
        if (pp.piece.type == PieceType::King && pp.piece.color == Color::Black) bk = pp.square;
    if (bk < 0) return false;
    for (const auto& p : s.plies)
        if (p.captured && (int)p.to == bk) return true;
    return false;
}

// A unit is captured on S, a later ply recaptures on S with the black king,
// and the black king is mated standing on S.
bool has_zajic(const Solution& s) {
    const Board& fin = final_board(s);
    int bk = -1;
    for (const auto& pp : fin.pieces())
        if (pp.piece.type == PieceType::King && pp.piece.color == Color::Black) bk = pp.square;
    if (bk < 0) return false;
    for (size_t i = 0; i < s.plies.size(); ++i) {
        if (!s.plies[i].captured || (int)s.plies[i].to != bk) continue;
        for (size_t j = i + 1; j < s.plies.size(); ++j) {
            const Ply& r = s.plies[j];
            if (r.captured && (int)r.to == bk && r.piece.type == PieceType::King &&
                r.piece.color == Color::Black)
                return true;
        }
    }
    return false;
}

// A unit of type T belonging to side C is captured, and a LATER ply promotes
// a pawn of side C to type T -- the captured unit is reborn.
bool has_phoenix(const Solution& s) {
    for (size_t i = 0; i < s.plies.size(); ++i) {
        const Ply& cap = s.plies[i];
        if (!cap.captured) continue;
        // The captured unit belongs to the side that did NOT move.
        const Color owner = cap.piece.color == Color::White ? Color::Black : Color::White;
        for (size_t j = i + 1; j < s.plies.size(); ++j) {
            const Ply& pr = s.plies[j];
            if (pr.promotion && *pr.promotion == *cap.captured && pr.piece.color == owner) return true;
        }
    }
    return false;
}

}  // namespace hm::themes
