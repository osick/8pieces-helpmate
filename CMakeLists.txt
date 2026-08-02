cmake_minimum_required(VERSION 3.24)

# The repo-root VERSION file is the single source of truth. CMake feeds it to
# project(), which feeds version.h and the cli_version test regex, so a
# release bump touches one file here instead of three.
file(READ ${CMAKE_CURRENT_SOURCE_DIR}/VERSION HELPMATE_VERSION_RAW)
string(STRIP "${HELPMATE_VERSION_RAW}" HELPMATE_VERSION_STR)
project(helpmate VERSION ${HELPMATE_VERSION_STR} LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE Release)
endif()
find_package(Threads REQUIRED)

# zstd is a hard requirement, deliberately a system package rather than a
# fourth FetchContent clone: this machine's gitconfig rewrites GitHub HTTPS to
# SSH, and a clone that hangs on an invisible passphrase dialog is far worse
# than a configure-time error that names the package to install.
find_package(PkgConfig QUIET)
if(PkgConfig_FOUND)
  pkg_check_modules(ZSTD IMPORTED_TARGET libzstd)
endif()
if(NOT ZSTD_FOUND)
  find_path(ZSTD_INCLUDE_DIR zstd.h)
  find_library(ZSTD_LIBRARY NAMES zstd)
  if(NOT ZSTD_INCLUDE_DIR OR NOT ZSTD_LIBRARY)
    message(FATAL_ERROR
      "libzstd headers not found -- install libzstd-devel (openSUSE) "
      "or libzstd-dev (Debian/Ubuntu)")
  endif()
  add_library(PkgConfig::ZSTD UNKNOWN IMPORTED)
  set_target_properties(PkgConfig::ZSTD PROPERTIES
    IMPORTED_LOCATION "${ZSTD_LIBRARY}"
    INTERFACE_INCLUDE_DIRECTORIES "${ZSTD_INCLUDE_DIR}")
endif()

# Declared early (before any add_library) so PIC applies to chessmg_core and
# helpmate_core too: pybind11_add_module below links helpmate_core into a
# shared object, which requires every static lib in its link chain to be
# position-independent.
option(HELPMATE_PYTHON "build python module" OFF)
if(HELPMATE_PYTHON)
  set(CMAKE_POSITION_INDEPENDENT_CODE ON)
endif()
option(HELPMATE_COVERAGE "coverage instrumentation" OFF)

include(FetchContent)
FetchContent_Declare(chessmg
  GIT_REPOSITORY https://github.com/osick/ChessMG.git
  GIT_TAG efbe11d9fe85ce186aadfbefa813818c03ae2c18)
FetchContent_Declare(catch2
  GIT_REPOSITORY https://github.com/catchorg/Catch2.git
  GIT_TAG v3.5.4)
FetchContent_Declare(json
  GIT_REPOSITORY https://github.com/nlohmann/json.git
  GIT_TAG v3.11.3)
FetchContent_MakeAvailable(chessmg catch2 json)

add_library(chessmg_core STATIC
  ${chessmg_SOURCE_DIR}/chessmg/libcmg/libsurge.cpp
  ${chessmg_SOURCE_DIR}/chessmg/libcmg/libcmg.cpp)
target_include_directories(chessmg_core SYSTEM PUBLIC ${chessmg_SOURCE_DIR}/chessmg/libcmg)
target_compile_options(chessmg_core PRIVATE -O2 -w)

enable_testing()

# Keep every executable at the top of the build tree. Without this, splitting
# the build into subdirectories moves them to build/src/core/helpmate_tests and
# build/src/packages/cli/helpmate -- which silently breaks every documented
# path (README, docs/BUILD.md, the Makefile's slowtest/test-core/test-cli
# targets, and CI's end-to-end smoke step), while ctest keeps passing because
# it resolves target locations itself. Worse, a pre-split build leaves stale
# binaries at the old paths, so the breakage is invisible in a dirty tree and
# only appears on a clean checkout.
set(CMAKE_RUNTIME_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR})

# Order matters: cli and bindings both link helpmate_core.
add_subdirectory(src/core)
add_subdirectory(src/packages/cli)
add_subdirectory(src/packages/bindings)
