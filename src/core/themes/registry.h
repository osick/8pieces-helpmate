#pragma once
#include <string>
#include <string_view>
#include <vector>

#include "probe/solution.h"

namespace hm::themes {

// A detector is a PURE function of a solution: no table access, no I/O. Every
// one is therefore testable against a hand-built position with no .hm file,
// and adding a theme is one function plus one registry entry.
using Detector = bool (*)(const Solution&);

struct ThemeDef {
    std::string_view name;
    Detector fn;
    std::string_view doc;  // the definition, shown by `helpmate themes`
};

// Every detector this build knows, in display order. CLI, API and dashboard
// all enumerate this rather than hard-coding names, so none of them needs
// touching when a theme is added.
const std::vector<ThemeDef>& theme_registry();

// nullptr when `name` is not registered. Matching is exact -- no case folding,
// no aliases: a near-miss should be an error naming the valid options, not a
// silent guess.
const ThemeDef* find_theme(std::string_view name);

// Names of every theme shown by AT LEAST ONE of `sols` -- the `any` semantics
// the query surface uses. Returned in registry order.
std::vector<std::string> detect(const std::vector<Solution>& sols);

}  // namespace hm::themes
