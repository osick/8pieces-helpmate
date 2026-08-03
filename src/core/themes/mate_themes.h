#pragma once
#include "probe/solution.h"

namespace hm::themes {

// Detectors that read only the mating position -- the board after the last
// ply, or the queried board itself when it was already mate. All four share
// the Detector signature so the registry stays uniform.
//
// PRECONDITION: none of these detectors verifies that the position is actually
// checkmate. is_pure and is_model in particular will happily return true for a
// position that is merely check -- e.g. "R5k1/8/6K1/8/8/8/8/r7 b - - 0 1",
// where Rxa8 refutes the check. In production this is harmless: every optimal
// solution this library produces ends at dtm 0, which is checkmate by
// construction. But a caller assembling a Solution by hand (not via the
// solver) can hand these detectors a merely-check position and get a false
// "pure"/"model" back. Callers doing that must check PosState::Checkmate
// themselves first.

// Every square of the black king's field is unavailable for EXACTLY ONE
// reason, and the king's own square is attacked exactly once. A square both
// occupied by a black unit and attacked by White is doing double duty and
// breaks purity; so does double check.
bool is_pure(const Solution& s);

// pure, and every white unit except the king and pawns participates --
// attacks the king's square or a field square, or stands on a field square.
bool is_model(const Solution& s);

// model, with no exemptions: the white king and white pawns must participate
// too, and every black unit other than the king must stand on a field square.
bool is_ideal(const Solution& s);

// Every square adjacent to the black king is empty, of either colour.
bool is_mirror(const Solution& s);

}  // namespace hm::themes
