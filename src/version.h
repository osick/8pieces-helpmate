#pragma once

namespace hm {

// Single source of truth for the version string embedded in the CLI
// (--version) and in every table's stats sidecar (generator_version).
// Keep in sync with pyproject.toml and CMakeLists.txt project(VERSION ...)
// on release bumps.
inline constexpr const char* HELPMATE_VERSION = "0.6.2";

}  // namespace hm
