#pragma once
#include "probe/solution.h"

namespace hm::themes {

// Detectors that walk one solution's plies. All share the Detector signature.

bool has_promotion(const Solution& s);       // any ply promotes a pawn
bool has_underpromotion(const Solution& s);  // any ply promotes to R, B or N

// A pawn standing on its OWN second rank at the start of the solution
// promotes during it.
bool has_excelsior(const Solution& s);
bool has_excelsior_white(const Solution& s);
bool has_excelsior_black(const Solution& s);

// A unit leaves a square and returns to it, having visited exactly one
// intermediate square (out and back).
bool has_switchback(const Solution& s);

// Rundlauf: a unit returns to its departure square having visited two or more
// DISTINCT intermediate squares, traversing a circuit rather than retracing
// its path. Mutually exclusive with switchback for a given return event, but
// one solution may show both, by different units.
bool has_closed_walk(const Solution& s);

// A black unit other than the king moves onto a square of the black king's
// field, and in the mating position that square holds that unit and is NOT
// attacked by White.
bool has_self_block(const Solution& s);

// Every move by that side is made by the same unit.
bool is_single_piece_white(const Solution& s);
bool is_single_piece_black(const Solution& s);
bool is_single_piece(const Solution& s);  // either side

bool has_en_passant(const Solution& s);  // any ply is an en-passant capture

// Some ply captures on square S, and in the mating position the black king
// stands on S.
bool has_kniest(const Solution& s);

}  // namespace hm::themes
