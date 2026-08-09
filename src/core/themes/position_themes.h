#pragma once
#include "themes/registry.h"

namespace hm::themes {

// Detectors that never enumerate solutions -- no walking the optimal-line
// tree -- which is what makes them the themes a query can answer on a
// saturated position. has_set_play reads one extra table value the caller
// already fetched for it (Needs::Plane) but still never touches `solutions`.

// The same position with the OTHER side to move is solvable. Cheap for a
// reason specific to this project: a cell index is independent of side to
// move -- side to move selects the PLANE, not the index -- so this is the
// same cell in the sibling plane, one extra byte from a read the scan is
// already doing. Absent input means the caller did not fetch it, and is
// answered "no": never guess a yes.
bool has_set_play(const ThemeInput& in);

}  // namespace hm::themes
