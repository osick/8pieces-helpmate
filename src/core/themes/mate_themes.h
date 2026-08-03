#pragma once
#include "probe/solution.h"

namespace hm::themes {

// Detectors that read only the mating position -- the board after the last
// ply, or the queried board itself when it was already mate. All four share
// the Detector signature so the registry stays uniform.

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
