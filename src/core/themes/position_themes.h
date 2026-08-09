#pragma once
#include "themes/registry.h"

namespace hm::themes {

// Detectors that never enumerate solutions -- no walking the optimal-line
// tree -- which is what makes them the themes a query can answer on a
// saturated position. has_set_play reads one extra table value the caller
// already fetched for it (Needs::Plane) but still never touches `solutions`.

// The same position with the OTHER side to move is solvable in exactly
// D - 1, where D is this position's own stored dtm: the mate is already
// available and the side to move merely delays it. A sibling at D + 1 is
// the OPPOSITE of set play -- flipping the side to move makes the mate
// LONGER, not available sooner -- and is deliberately excluded, which is
// why this detector needs the position's own value, not just the sibling's.
// (The looser "sibling solvable at any shorter distance" reading is the
// separate *Short set play* notion; not implemented here.)
// Cheap for a reason specific to this project: a cell index is independent
// of side to move -- side to move selects the PLANE, not the index -- so
// the sibling is the same cell in the sibling plane, one extra byte from a
// read the scan is already doing. Absent input means the caller did not
// fetch it, and is answered "no": never guess a yes.
bool has_set_play(const ThemeInput& in);

}  // namespace hm::themes
