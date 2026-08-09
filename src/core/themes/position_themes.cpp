#include "themes/position_themes.h"

namespace hm::themes {

bool has_set_play(const ThemeInput& in) {
    // Written as other+1==value, not value-1==other: value.dtm is a uint8_t
    // and this position can itself be mate (dtm 0), where value.dtm - 1
    // would underflow to 255 (DTM_UNSOLVABLE) and silently compare true
    // against the wrong thing instead of just being false.
    return in.other_plane.has_value() && in.other_plane->dtm <= DTM_MAX && in.value.dtm <= DTM_MAX &&
           in.other_plane->dtm + 1 == in.value.dtm;
}

}  // namespace hm::themes
