#include "themes/registry.h"

#include "themes/line_themes.h"
#include "themes/mate_themes.h"

namespace hm::themes {

const std::vector<ThemeDef>& theme_registry() {
    static const std::vector<ThemeDef> kRegistry = {
        {"pure", &any_of<&is_pure>,
         "Pure mate: every square of the black king's field is unavailable for "
         "exactly one reason, and the king's square is attacked exactly once "
         "(so double check is impure).",
         Needs::Solutions},
        {"model", &any_of<&is_model>,
         "Model mate: pure, and every white unit except the king and pawns "
         "participates -- attacks the king's square or a field square, or "
         "stands on one.",
         Needs::Solutions},
        {"ideal", &any_of<&is_ideal>,
         "Ideal mate: model with no exemptions -- the white king and white "
         "pawns must participate too, and every black unit other than the king "
         "must stand on a field square.",
         Needs::Solutions},
        {"mirror", &any_of<&is_mirror>,
         "Mirror mate: every square adjacent to the black king is empty, of "
         "either colour.",
         Needs::Solutions},
        {"promotion", &any_of<&has_promotion>, "A pawn promotes during the solution.", Needs::Solutions},
        {"underpromotion", &any_of<&has_underpromotion>, "A pawn promotes to rook, bishop or knight.",
         Needs::Solutions},
        {"excelsior", &any_of<&has_excelsior>,
         "A pawn standing on its own second rank at the start of the solution "
         "promotes during it (either colour).",
         Needs::Solutions},
        {"excelsior:white", &any_of<&has_excelsior_white>, "Excelsior by a white pawn.", Needs::Solutions},
        {"excelsior:black", &any_of<&has_excelsior_black>, "Excelsior by a black pawn.", Needs::Solutions},
        {"switchback", &any_of<&has_switchback>,
         "A unit leaves a square and returns to it, having visited exactly one "
         "intermediate square.",
         Needs::Solutions},
        {"closed-walk", &any_of<&has_closed_walk>,
         "Rundlauf: a unit returns to its departure square having visited two "
         "or more distinct intermediate squares, so it traverses a circuit "
         "rather than retracing its path.",
         Needs::Solutions},
        {"self-block", &any_of<&has_self_block>,
         "A black unit other than the king moves onto a square of its own "
         "king's field and stands there unattacked in the mating position, "
         "blocking a flight square.",
         Needs::Solutions},
        {"single-piece", &any_of<&is_single_piece>,
         "Every move by one side is made by the same unit (either side).", Needs::Solutions},
        {"single-piece:white", &any_of<&is_single_piece_white>, "Every white move is made by the same unit.",
         Needs::Solutions},
        {"single-piece:black", &any_of<&is_single_piece_black>,
         "Every black move is made by the same unit; with the king, this is "
         "the Analyzer's 'BK moves only'.",
         Needs::Solutions},
        {"en-passant", &any_of<&has_en_passant>, "A ply is an en-passant capture.", Needs::Solutions},
    };
    return kRegistry;
}

const ThemeDef* find_theme(std::string_view name) {
    for (const auto& t : theme_registry())
        if (t.name == name) return &t;
    return nullptr;
}

std::vector<std::string> detect(const ThemeInput& in) {
    std::vector<std::string> out;
    for (const auto& t : theme_registry())
        if (t.fn(in)) out.emplace_back(t.name);
    return out;
}

}  // namespace hm::themes
