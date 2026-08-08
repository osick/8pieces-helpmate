#pragma once
#include "themes/registry.h"

namespace hm::themes {

// Detectors that read the DIAGRAM only -- no solutions, no table. These are
// the themes a query can answer without enumerating, which also makes them
// the only themes that can answer on a saturated position.

// Every unit stands on a square it occupies in the initial game array for its
// own colour and type. Pawns count anywhere on their home rank: requiring the
// file would make the theme useless, and the sense of the name is "nothing has
// left home yet".
bool is_homebase(const ThemeInput& in);

}  // namespace hm::themes
