#pragma once
#include <optional>
#include <string>
#include <string_view>
#include <vector>

#include "chess/types.h"
#include "probe/solution.h"

namespace hm::themes {

// What a detector must be given. Ordered by cost: a query needs only the
// most expensive input any of its themes asks for.
enum class Needs : uint8_t { Position = 0, Plane = 1, Solutions = 2 };

// The wire/display name of a Needs value. Defined once: every surface that
// reports `needs` uses this, so adding a fourth value cannot silently fall
// through to "solutions" in one surface and not another.
constexpr std::string_view needs_name(Needs n) {
    switch (n) {
        case Needs::Position:
            return "position";
        case Needs::Plane:
            return "plane";
        case Needs::Solutions:
            return "solutions";
    }
    return "solutions";
}

// Everything a detector may read. The CALLER fetches; the detector stays a
// pure function, so it is still testable against a hand-built position with
// no .hm file on disk. `solutions` is empty unless some theme needs it, and
// `other_plane` is nullopt unless some theme needs it. `value` is this
// position's own stored dtm/count -- needed by detectors (set-play) that
// compare the sibling plane against the position's OWN distance, not merely
// its solvability.
struct ThemeInput {
    const Board& start;
    ValuePair value;
    std::optional<ValuePair> other_plane;
    const std::vector<Solution>& solutions;
};

using Detector = bool (*)(const ThemeInput&);

struct ThemeDef {
    std::string_view name;
    Detector fn;
    std::string_view doc;  // the definition, shown by `helpmate themes`
    Needs needs;
};

// Adapts a per-solution detector to the registry signature, supplying the
// `any` the query surface uses. This is the ONLY place `any` is expressed.
template <bool (*F)(const Solution&)>
bool any_of(const ThemeInput& in) {
    for (const auto& s : in.solutions)
        if (F(s)) return true;
    return false;
}

// Every detector this build knows, in display order. CLI, API and dashboard
// all enumerate this rather than hard-coding names, so none of them needs
// touching when a theme is added.
const std::vector<ThemeDef>& theme_registry();

// nullptr when `name` is not registered. Matching is exact -- no case folding,
// no aliases: a near-miss should be an error naming the valid options, not a
// silent guess.
const ThemeDef* find_theme(std::string_view name);

// Names of every theme shown by `in` -- the `any` semantics the query surface
// uses (via any_of<>, for solution-based detectors). Returned in registry order.
std::vector<std::string> detect(const ThemeInput& in);

}  // namespace hm::themes
