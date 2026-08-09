#include "themes/position_themes.h"

namespace hm::themes {

bool has_set_play(const ThemeInput& in) {
    // Written as other+1==value rather than value-1==other. Not because the
    // subtraction would wrap: uint8_t promotes to int before the arithmetic,
    // so value.dtm - 1 at dtm 0 is -1, not 255, and simply never compares
    // equal (verified with g++ 13 -O2). The addition is preferred because it
    // needs no promotion reasoning at all -- both operands are already bounded
    // to [0, 252] by the guards above, so other+1 <= 253 is trivially in range
    // whatever the types do, and the expression reads as what it means: the
    // sibling is exactly one ply shorter.
    return in.other_plane.has_value() && in.other_plane->dtm <= DTM_MAX && in.value.dtm <= DTM_MAX &&
           in.other_plane->dtm + 1 == in.value.dtm;
}

}  // namespace hm::themes
