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

// A unit is captured on square S, a later ply recaptures on S with the black
// king, and the black king is mated standing on S.
bool has_zajic(const Solution& s);

// A unit of type T belonging to side C is captured, and a LATER ply promotes
// a pawn of side C to type T -- the captured unit is reborn.
bool has_phoenix(const Solution& s);

// A pawn promotes on square S; a later ply captures on S; and no ply in
// between moves a unit FROM S. The promoted unit is captured without ever
// having moved.
bool has_schnoebelen(const Solution& s);

// One unit's trajectory visits exactly two distinct squares and has length
// >= 4 -- A,B,A,B, at least two returns. Deliberately NOT exclusive with
// switchback: a pendulum trajectory contains a switchback (A,B,A), and both
// are reported.
bool has_pendulum(const Solution& s);

}  // namespace hm::themes
