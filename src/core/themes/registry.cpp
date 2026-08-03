#include "themes/registry.h"
#include "themes/line_themes.h"
#include "themes/mate_themes.h"

namespace hm::themes {

const std::vector<ThemeDef>& theme_registry() {
    static const std::vector<ThemeDef> kRegistry = {
        {"pure", &is_pure,
         "Pure mate: every square of the black king's field is unavailable for "
         "exactly one reason, and the king's square is attacked exactly once "
         "(so double check is impure)."},
        {"model", &is_model,
         "Model mate: pure, and every white unit except the king and pawns "
         "participates -- attacks the king's square or a field square, or "
         "stands on one."},
        {"ideal", &is_ideal,
         "Ideal mate: model with no exemptions -- the white king and white "
         "pawns must participate too, and every black unit other than the king "
         "must stand on a field square."},
        {"mirror", &is_mirror,
         "Mirror mate: every square adjacent to the black king is empty, of "
         "either colour."},
        {"promotion", &has_promotion, "A pawn promotes during the solution."},
        {"underpromotion", &has_underpromotion,
         "A pawn promotes to rook, bishop or knight."},
        {"excelsior", &has_excelsior,
         "A pawn standing on its own second rank at the start of the solution "
         "promotes during it (either colour)."},
        {"excelsior:white", &has_excelsior_white, "Excelsior by a white pawn."},
        {"excelsior:black", &has_excelsior_black, "Excelsior by a black pawn."},
        {"switchback", &has_switchback,
         "A unit leaves a square and returns to it, having visited exactly one "
         "intermediate square."},
        {"closed-walk", &has_closed_walk,
         "Rundlauf: a unit returns to its departure square having visited two "
         "or more distinct intermediate squares, so it traverses a circuit "
         "rather than retracing its path."},
        {"self-block", &has_self_block,
         "A black unit other than the king moves onto a square of its own "
         "king's field and stands there unattacked in the mating position, "
         "blocking a flight square."},
        {"single-piece", &is_single_piece,
         "Every move by one side is made by the same unit (either side)."},
        {"single-piece:white", &is_single_piece_white,
         "Every white move is made by the same unit."},
        {"single-piece:black", &is_single_piece_black,
         "Every black move is made by the same unit; with the king, this is "
         "the Analyzer's 'BK moves only'."},
        {"en-passant", &has_en_passant, "A ply is an en-passant capture."},
    };
    return kRegistry;
}

const ThemeDef* find_theme(std::string_view name) {
    for (const auto& t : theme_registry())
        if (t.name == name) return &t;
    return nullptr;
}

std::vector<std::string> detect(const std::vector<Solution>& sols) {
    std::vector<std::string> out;
    for (const auto& t : theme_registry())
        for (const auto& s : sols)
            if (t.fn(s)) {
                out.emplace_back(t.name);
                break;                        // `any`: one solution is enough
            }
    return out;
}

}  // namespace hm::themes
