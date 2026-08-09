#include "themes/position_themes.h"

namespace hm::themes {

bool has_set_play(const ThemeInput& in) {
    return in.other_plane.has_value() && in.other_plane->dtm <= DTM_MAX;
}

}  // namespace hm::themes
