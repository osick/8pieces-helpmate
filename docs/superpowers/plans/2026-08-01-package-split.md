# Package Split (v0.7.1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reorganise the repo into three separately installable distributions — `helpmate` (C++ core + CLI binary + Python bindings), `helpmate-api`, `helpmate-web` — with each package owning its own build file and test suite.

**Architecture:** One monorepo, four package directories. A thin root `CMakeLists.txt` delegates to `src/core/`, `src/packages/cli/` and `src/packages/bindings/`; the two pure-Python distributions build with hatchling from their own `pyproject.toml`. The dashboard becomes a Python package (`helpmate_web`) whose `static_dir()` the API imports, replacing today's filesystem path guessing. A single `VERSION` file feeds CMake and is held consistent with the three `pyproject.toml` literals by a test.

**Tech Stack:** C++20, CMake ≥ 3.24, scikit-build-core, pybind11, hatchling, FastAPI, pytest, Catch2, Node's built-in test runner, Playwright.

Spec: `docs/superpowers/specs/2026-08-01-package-split-design.md`

**Branch.** All seven tasks land on `v0.7.1-packages`, cut from `main` at the
v0.7.0 merge. Create it before Task 1:

```bash
git checkout main && git checkout -b v0.7.1-packages
```

## Global Constraints

- **Max 4 cores for every local build and test command.** Prefix with `taskset -c 0-3`.
- **Never touch `~/tb`.** A long 6-piece generation writes there. Use `$(mktemp -d)` for every scratch tables dir.
- **Never run bare `./build/helpmate_tests`** — that adds the 30–60 minute `[slow]` lane. Always `./build/helpmate_tests "~[slow]"`.
- **Never let CMake FetchContent clone from GitHub.** `build/_deps` is already populated; a fresh clone triggers the user's HTTPS→SSH gitconfig rewrite and a passphrase window. Reconfigure in place; if a clean configure is unavoidable, pass `-DFETCHCONTENT_FULLY_DISCONNECTED=ON` plus the three `-DFETCHCONTENT_SOURCE_DIR_*` flags shown in `docs/BUILD.md`.
- **Every file move uses `git mv`**, never copy-then-delete, so history follows the file.
- **Version for this release: `0.7.1`.** No git tag and no GitHub release.
- **Commit trailer** on every commit: `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`
- **Every task must end with the full suite green.** No task may leave a broken intermediate state.
- **The ctest total is exactly 117** (86 Catch2 + 31 CLI). A different number after any task means a test was lost.
- License is MIT; use `license = {text = "MIT"}` in the new `pyproject.toml` files — a `{file = ...}` path pointing outside the package directory is rejected by hatchling.

---

### Task 1: Single-source the version

Introduces the `VERSION` file, generates `version.h` from it, derives the `cli_version` ctest regex from it, and adds the test that keeps the three `pyproject.toml` literals honest. Done first because it is independent of every move and makes the 0.7.1 bump verifiable rather than manual.

**Files:**
- Create: `VERSION`
- Create: `src/version.h.in`
- Delete: `src/version.h`
- Create: `tests/repo/test_version_consistency.py`
- Modify: `CMakeLists.txt` (lines 1–2, and the `cli_version` property near the end)
- Modify: `pyproject.toml` (version literal)
- Modify: `server/helpmate_server/__init__.py`
- Modify: `src/bindings/pymodule.cpp` (expose `__version__`)

**Interfaces:**
- Consumes: nothing.
- Produces: a `VERSION` file at the repo root containing `0.7.1\n`; `helpmate.__version__` (str); the CMake variable `PROJECT_VERSION`.

- [ ] **Step 1: Write the failing test**

Create `tests/repo/test_version_consistency.py`:

```python
"""Every declared version must equal the VERSION file.

This is the one suite that is deliberately not colocated with a package: it
is a statement about the repo, not about any single package. Six places have
carried the version by hand, and two of them have been missed on a release.
"""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PYPROJECTS = [
    ROOT / "pyproject.toml",
    ROOT / "src" / "packages" / "api" / "pyproject.toml",
    ROOT / "src" / "packages" / "web" / "pyproject.toml",
]


def declared_version(pyproject: Path) -> str:
    # Deliberately not tomllib: the project declares a 3.9 floor and tomllib
    # only arrived in 3.11.
    section = pyproject.read_text().split("[project]", 1)[1]
    m = re.search(r'^version\s*=\s*"([^"]+)"', section, re.M)
    assert m, f"no [project] version in {pyproject}"
    return m.group(1)


@pytest.fixture(scope="session")
def version() -> str:
    return (ROOT / "VERSION").read_text().strip()


def test_version_file_is_a_bare_version(version):
    assert re.fullmatch(r"\d+\.\d+\.\d+", version), version


@pytest.mark.parametrize("pyproject", PYPROJECTS, ids=lambda p: p.parent.name)
def test_pyproject_matches_version_file(pyproject, version):
    if not pyproject.exists():
        pytest.skip(f"{pyproject} does not exist yet")
    assert declared_version(pyproject) == version


def test_python_bindings_match_version_file(version):
    import helpmate
    assert helpmate.__version__ == version


def test_server_matches_version_file(version):
    helpmate_server = pytest.importorskip("helpmate_server")
    assert helpmate_server.__version__ == version


def test_cli_binary_matches_version_file(version):
    exe = shutil.which("helpmate") or str(ROOT / "build" / "helpmate")
    if not Path(exe).exists():
        pytest.skip("helpmate binary not built or installed")
    out = subprocess.run([exe, "--version"], capture_output=True, text=True).stdout
    assert version in out, out
```

- [ ] **Step 2: Run it to verify it fails**

Run: `taskset -c 0-3 python3 -m pytest tests/repo -v`
Expected: FAIL — `VERSION` does not exist (`FileNotFoundError`), and `helpmate.__version__` raises `AttributeError`.

- [ ] **Step 3: Create the VERSION file**

Create `VERSION` containing exactly one line:

```
0.7.1
```

- [ ] **Step 4: Generate version.h from it**

`git rm src/version.h`, then create `src/version.h.in`:

```cpp
#pragma once

namespace hm {

// Single source of truth for the version string reported by the CLI
// (--version) and written into every table's stats sidecar
// (generator_version). Generated by CMake from the repo-root VERSION file --
// do not edit the generated copy under build/generated/.
inline constexpr const char* HELPMATE_VERSION = "@PROJECT_VERSION@";

}  // namespace hm
```

In `CMakeLists.txt`, replace lines 1–2 with:

```cmake
cmake_minimum_required(VERSION 3.24)

# The repo-root VERSION file is the single source of truth. CMake feeds it to
# project(), which feeds version.h and the cli_version test regex below, so a
# release bump touches one file here instead of three.
file(READ ${CMAKE_CURRENT_SOURCE_DIR}/VERSION HELPMATE_VERSION_RAW)
string(STRIP "${HELPMATE_VERSION_RAW}" HELPMATE_VERSION_STR)
project(helpmate VERSION ${HELPMATE_VERSION_STR} LANGUAGES CXX)
```

Immediately after the `add_library(helpmate_core ...)` line, add:

```cmake
configure_file(${CMAKE_CURRENT_SOURCE_DIR}/src/version.h.in
               ${CMAKE_BINARY_DIR}/generated/version.h @ONLY)
target_include_directories(helpmate_core PUBLIC ${CMAKE_BINARY_DIR}/generated)
```

Replace the `cli_version` property line with:

```cmake
# Regex-escape the dots so 0.7.1 does not also match 0X7Y1.
string(REPLACE "." "\\." HELPMATE_VERSION_RE "${PROJECT_VERSION}")
set_tests_properties(cli_version PROPERTIES PASS_REGULAR_EXPRESSION "helpmate ${HELPMATE_VERSION_RE}")
```

- [ ] **Step 5: Expose the version to Python**

In `src/bindings/pymodule.cpp`, add near the top with the other includes:

```cpp
#include "version.h"
```

and inside the `PYBIND11_MODULE(_helpmate, m)` body, as the first statement:

```cpp
    m.attr("__version__") = hm::HELPMATE_VERSION;
```

In `python/helpmate/__init__.py`, change the import line and `__all__`:

```python
from ._helpmate import (
    Tablebase as _Tablebase, generate, MissingTableError, __version__,
)
```

```python
__all__ = ["Tablebase", "generate", "MissingTableError", "__version__"]
```

- [ ] **Step 6: Bump the two Python literals**

`pyproject.toml`: `version = "0.7.1"`.
`server/helpmate_server/__init__.py`: `__version__ = "0.7.1"`.

- [ ] **Step 7: Rebuild and verify**

```bash
taskset -c 0-3 cmake --build build -j4
taskset -c 0-3 ctest --test-dir build --output-on-failure | tail -3
```

Expected: `100% tests passed, 0 tests failed out of 117`.

```bash
CC=gcc-13 CXX=g++-13 taskset -c 0-3 python3 -m pip install -e . -q
taskset -c 0-3 python3 -m pytest tests/repo -v
```

Expected: all pass; the two not-yet-existing `pyproject.toml` parametrisations SKIP.

- [ ] **Step 8: Commit**

```bash
git add VERSION src/version.h.in tests/repo CMakeLists.txt pyproject.toml \
        server/helpmate_server/__init__.py src/bindings/pymodule.cpp python/helpmate/__init__.py
git rm --cached src/version.h 2>/dev/null || true
git commit -m "build: single-source the version from a VERSION file

version.h is generated from it, the cli_version ctest regex is derived from
PROJECT_VERSION instead of hardcoding the number, the bindings expose
__version__, and a repo-level test asserts every declared version agrees.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Move the C++ sources into the package tree

Pure `git mv` plus path updates in the single root `CMakeLists.txt`. The CMake *split* is Task 3 — doing both at once makes a failure impossible to attribute.

**Files:**
- Move: `src/{chess,indexing,format,generator,probe}/` → `src/core/{...}/`
- Move: `src/version.h.in` → `src/core/version.h.in`
- Move: `src/cli/main.cpp` → `src/packages/cli/main.cpp`
- Move: `src/bindings/pymodule.cpp` → `src/packages/bindings/pymodule.cpp`
- Move: `tests/cpp/test_*.cpp` → `src/core/tests/`
- Move: `tests/cpp/mk_legacy_table.cpp`, `tests/cpp/assert_absent.cmake` → `src/packages/cli/tests/`
- Modify: `CMakeLists.txt`

**Interfaces:**
- Consumes: `VERSION`, `PROJECT_VERSION` from Task 1.
- Produces: the source layout every later task's paths assume. `helpmate_core`'s public include dir becomes `src/core`, so `#include "chess/board.h"` etc. keep resolving unchanged.

- [ ] **Step 1: Move the core, CLI and bindings sources**

```bash
mkdir -p src/core src/packages/cli src/packages/bindings
git mv src/chess src/indexing src/format src/generator src/probe src/core/
git mv src/version.h.in src/core/version.h.in
git mv src/cli/main.cpp src/packages/cli/main.cpp && rmdir src/cli
git mv src/bindings/pymodule.cpp src/packages/bindings/pymodule.cpp && rmdir src/bindings
```

- [ ] **Step 2: Move the C++ test files**

```bash
mkdir -p src/core/tests src/packages/cli/tests
git mv tests/cpp/mk_legacy_table.cpp tests/cpp/assert_absent.cmake src/packages/cli/tests/
git mv tests/cpp/*.cpp src/core/tests/
rmdir tests/cpp
```

- [ ] **Step 3: Update every path in the root CMakeLists.txt**

Four edits, all mechanical:

```cmake
set(HELPMATE_SOURCES src/core/chess/board.cpp src/core/chess/san.cpp src/core/indexing/material.cpp src/core/indexing/kk.cpp src/core/indexing/slice_index.cpp src/core/format/table_file.cpp src/core/generator/oracle.cpp src/core/generator/generator.cpp src/core/probe/tablebase.cpp)  # tasks append here
```

```cmake
target_include_directories(helpmate_core PUBLIC src/core)
```

```cmake
configure_file(${CMAKE_CURRENT_SOURCE_DIR}/src/core/version.h.in
               ${CMAKE_BINARY_DIR}/generated/version.h @ONLY)
```

The `helpmate_tests` executable's source list: replace every `tests/cpp/` with `src/core/tests/`. The `helpmate` executable: `src/packages/cli/main.cpp`. `mk_legacy_table`: `src/packages/cli/tests/mk_legacy_table.cpp`. `pybind11_add_module`: `src/packages/bindings/pymodule.cpp`. The `assert_absent.cmake` reference: `${CMAKE_SOURCE_DIR}/src/packages/cli/tests/assert_absent.cmake`.

- [ ] **Step 4: Reconfigure and verify the count is still 117**

```bash
taskset -c 0-3 cmake -S . -B build
taskset -c 0-3 cmake --build build -j4
taskset -c 0-3 ctest --test-dir build --output-on-failure | tail -3
```

Expected: `100% tests passed, 0 tests failed out of 117`. **If the total is not 117, stop and find the missing test before continuing.**

```bash
taskset -c 0-3 ./build/helpmate_tests "~[slow]" | tail -2
```

Expected: `All tests passed (... assertions in 86 test cases)`.

- [ ] **Step 5: Verify the Python side still builds against the moved sources**

```bash
CC=gcc-13 CXX=g++-13 taskset -c 0-3 python3 -m pip install -e . -q
taskset -c 0-3 python3 -m pytest tests/python tests/server tests/repo -q | tail -3
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "refactor: move C++ sources into src/core and src/packages

git mv only -- no code changes. The core library, the CLI's main.cpp, the
pybind11 module and the two C++ test suites move to the directories that will
own them; the root CMakeLists is repointed. ctest still registers 117 cases.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Split the root CMakeLists into per-package build files

**Files:**
- Create: `src/core/CMakeLists.txt`
- Create: `src/packages/cli/CMakeLists.txt`
- Create: `src/packages/bindings/CMakeLists.txt`
- Modify: `CMakeLists.txt` (shrinks to the aggregator)

**Interfaces:**
- Consumes: the layout from Task 2; `PROJECT_VERSION` and `HELPMATE_VERSION_RE` from Task 1.
- Produces: CMake targets `helpmate_core` (library), `helpmate` (executable), `mk_legacy_table` (executable), `_helpmate` (module, when `HELPMATE_PYTHON=ON`). All are declared in subdirectories but visible globally, so `add_subdirectory` order is: core, cli, bindings.

- [ ] **Step 1: Move the core into src/core/CMakeLists.txt**

Cut from the root file into `src/core/CMakeLists.txt`: the `HELPMATE_SOURCES` list, `add_library(helpmate_core ...)`, the `configure_file` + `target_include_directories` + `target_link_libraries` + `target_compile_options` for it, the `HELPMATE_COVERAGE` block, the `helpmate_tests` executable, the `CMAKE_MODULE_PATH`/`include(Catch)`/`catch_discover_tests` block.

Paths become relative to `src/core/`, so drop the `src/core/` prefix everywhere:

```cmake
# The helpmate core: board representation, symmetry-reduced indexing, the
# table format, the generator and the probe library. Everything else in the
# repo is a client of this.
set(HELPMATE_SOURCES chess/board.cpp chess/san.cpp indexing/material.cpp indexing/kk.cpp indexing/slice_index.cpp format/table_file.cpp generator/oracle.cpp generator/generator.cpp probe/tablebase.cpp)  # tasks append here
add_library(helpmate_core STATIC ${HELPMATE_SOURCES})

configure_file(${CMAKE_CURRENT_SOURCE_DIR}/version.h.in
               ${CMAKE_BINARY_DIR}/generated/version.h @ONLY)

target_include_directories(helpmate_core PUBLIC
  ${CMAKE_CURRENT_SOURCE_DIR} ${CMAKE_BINARY_DIR}/generated)
target_link_libraries(helpmate_core PUBLIC chessmg_core nlohmann_json::nlohmann_json Threads::Threads)
target_compile_options(helpmate_core PRIVATE -O2 -Wall -Wextra)

if(HELPMATE_COVERAGE)
  target_compile_options(helpmate_core PRIVATE --coverage -O0 -g)
  target_link_options(helpmate_core PUBLIC --coverage)
endif()

add_executable(helpmate_tests
  tests/test_sanity.cpp tests/test_board.cpp tests/test_san.cpp
  tests/test_material.cpp tests/test_kk.cpp tests/test_slice_index.cpp
  tests/test_table_file.cpp tests/test_oracle.cpp tests/test_generator_init.cpp
  tests/test_generator_kqvk.cpp tests/test_generator_pawns.cpp
  tests/test_counts.cpp tests/test_stats.cpp tests/test_threads.cpp
  tests/test_probe.cpp tests/test_generator_lookup_guards.cpp
  tests/test_ram_guard.cpp tests/test_slice_index_6piece.cpp
  tests/test_generator_prune.cpp)
target_link_libraries(helpmate_tests PRIVATE helpmate_core Catch2::Catch2WithMain)
list(APPEND CMAKE_MODULE_PATH ${catch2_SOURCE_DIR}/extras)
include(Catch)
# Slow cases (full KPvkp closure generation) are excluded from ctest here.
# Run them with: ./build/helpmate_tests "[slow]"
catch_discover_tests(helpmate_tests TEST_SPEC "~[slow]")
```

Note: `test_sanity.cpp` through `test_generator_prune.cpp` is the exact list from the root file — copy it from there rather than retyping, and confirm it has 19 entries.

- [ ] **Step 2: Move the CLI into src/packages/cli/CMakeLists.txt**

Cut into `src/packages/cli/CMakeLists.txt`: the `helpmate` executable, both install rules, `mk_legacy_table`, and **all 31** `add_test` / `set_tests_properties` declarations verbatim, changing only `${CMAKE_SOURCE_DIR}/tests/cpp/assert_absent.cmake` to `${CMAKE_CURRENT_SOURCE_DIR}/tests/assert_absent.cmake`. Header:

```cmake
# The `helpmate` command-line client, and the end-to-end ctest cases that
# drive the real binary. These are the only tests that exercise argument
# parsing, exit codes and the printed output a user actually sees.
add_executable(helpmate main.cpp)
target_link_libraries(helpmate PRIVATE helpmate_core)

# Two install destinations, never both: SKBUILD_SCRIPTS_DIR is defined only
# when scikit-build-core is building a wheel, and puts the binary on PATH for
# `pip install helpmate`. A plain `cmake --install` uses bin/ as before.
if(DEFINED SKBUILD_SCRIPTS_DIR)
  install(TARGETS helpmate RUNTIME DESTINATION ${SKBUILD_SCRIPTS_DIR})
else()
  install(TARGETS helpmate RUNTIME DESTINATION bin)
endif()

# Test-support only (not installed): writes a legacy-format all-unsolvable
# table so `helpmate compact`'s ctest coverage has a real rewrite target --
# see tests/mk_legacy_table.cpp for why `helpmate gen` can no longer produce
# this fixture itself.
add_executable(mk_legacy_table tests/mk_legacy_table.cpp)
target_link_libraries(mk_legacy_table PRIVATE helpmate_core)
```

- [ ] **Step 3: Move the bindings into src/packages/bindings/CMakeLists.txt**

```cmake
# The pybind11 extension. Off by default; scikit-build-core turns it on via
# cmake.define.HELPMATE_PYTHON in the root pyproject.toml.
if(HELPMATE_PYTHON)
  find_package(pybind11 CONFIG REQUIRED)
  pybind11_add_module(_helpmate pymodule.cpp)
  target_link_libraries(_helpmate PRIVATE helpmate_core)
  install(TARGETS _helpmate DESTINATION helpmate)
endif()
```

- [ ] **Step 4: Reduce the root CMakeLists to the aggregator**

The whole file, after the edit:

```cmake
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

# Order matters: cli and bindings both link helpmate_core.
add_subdirectory(src/core)
add_subdirectory(src/packages/cli)
add_subdirectory(src/packages/bindings)
```

- [ ] **Step 5: Reconfigure and verify the count is still 117**

```bash
rm -rf build/CMakeCache.txt build/CMakeFiles
taskset -c 0-3 cmake -S . -B build
taskset -c 0-3 cmake --build build -j4
taskset -c 0-3 ctest --test-dir build --output-on-failure | tail -3
```

Expected: `100% tests passed, 0 tests failed out of 117`.

Then confirm the split preserved the two groups:

```bash
taskset -c 0-3 ctest --test-dir build -N | grep -c "Test *#"
taskset -c 0-3 ctest --test-dir build -N -R "^cli_" | grep -c "Test *#"
```

Expected: `117` and `31`.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "build: split CMakeLists into per-package build files

The root file keeps only what is global -- project(), the C++ standard, the
FetchContent pins, the two options and enable_testing() -- and delegates to
src/core, src/packages/cli and src/packages/bindings. Each package now
declares its own targets and its own tests. Adds the SKBUILD_SCRIPTS_DIR
install destination so a wheel can carry the CLI binary.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Make the root distribution `helpmate` (core + CLI + bindings)

**Files:**
- Move: `python/helpmate/` → `src/packages/bindings/helpmate/`
- Move: `tests/python/` → `src/packages/bindings/tests/`
- Modify: `pyproject.toml`

**Interfaces:**
- Consumes: the `SKBUILD_SCRIPTS_DIR` install rule from Task 3.
- Produces: a `helpmate` wheel containing the `helpmate` Python package, the `_helpmate` extension, and the `helpmate` CLI binary on PATH. `helpmate.__version__` equals the `VERSION` file.

- [ ] **Step 1: Move the Python package and its tests**

```bash
git mv python/helpmate src/packages/bindings/helpmate && rmdir python
git mv tests/python src/packages/bindings/tests
```

- [ ] **Step 2: Point pyproject at the new location and drop the server/web packages**

`pyproject.toml` becomes:

```toml
[build-system]
requires = ["scikit-build-core>=0.9", "pybind11>=2.12"]
build-backend = "scikit_build_core.build"

[project]
name = "helpmate"
version = "0.7.1"
description = "Helpmate tablebases: cooperative mate distances and solution counts"
requires-python = ">=3.9"
license = {text = "MIT"}

[project.optional-dependencies]
dev = ["pytest", "chess>=1.10"]

[tool.scikit-build]
cmake.version = ">=3.24"
wheel.packages = ["src/packages/bindings/helpmate"]
cmake.define.HELPMATE_PYTHON = "ON"
```

The `server` extra and the two console scripts are gone: they belong to
`helpmate-api` now (Task 6). `httpx` and `playwright` move to that package's
and the web package's `dev` extras.

- [ ] **Step 3: Reinstall and check the binary lands on PATH**

```bash
CC=gcc-13 CXX=g++-13 taskset -c 0-3 python3 -m pip install -e . -q
taskset -c 0-3 python3 -m pytest src/packages/bindings/tests tests/repo -q | tail -3
```

Expected: all pass.

An editable install does not exercise `SKBUILD_SCRIPTS_DIR`, so verify it with a real wheel in a throwaway venv:

```bash
V="$(mktemp -d)/venv"; python3 -m venv "$V"
CC=gcc-13 CXX=g++-13 taskset -c 0-3 "$V/bin/pip" install . -q
"$V/bin/helpmate" --version
"$V/bin/python" -c "import helpmate; print(helpmate.__version__)"
```

Expected: both print `0.7.1` (the binary as `helpmate 0.7.1`). **If `helpmate` is not found, `SKBUILD_SCRIPTS_DIR` is not being set by this scikit-build-core version — check `pip install . -v` output for the install prefix and adjust the `if(DEFINED ...)` guard before continuing.**

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "build: helpmate is now core + CLI binary + bindings only

The Python package and its tests move under src/packages/bindings, the wheel
carries the compiled CLI so \`pip install helpmate\` puts it on PATH, and the
server/web packages and the [server] extra leave this distribution.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Create the `helpmate-web` distribution

Moves the dashboard into a Python package and teaches the API to locate it by import rather than by path arithmetic. Both halves are in one task because splitting them would leave the dashboard unserved in between.

**Files:**
- Move: `web/*` → `src/packages/web/helpmate_web/static/`
- Create: `src/packages/web/helpmate_web/__init__.py`
- Create: `src/packages/web/pyproject.toml`
- Move: `tests/js/` → `src/packages/web/tests/js/`
- Move: `tests/ui/` → `src/packages/web/tests/ui/`
- Modify: `src/packages/web/tests/js/*.test.js` (relative import paths)
- Modify: `.gitignore` (the two `lib/` negations)
- Modify: `Makefile` (`jstest` glob)
- Modify: `server/helpmate_server/app.py` (static resolution)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `helpmate_web.static_dir() -> pathlib.Path`, the directory holding `index.html`, `css/`, `js/` and `vendor/`. `create_app(chain, mine_cap, mine_timeout, web_root=None, serve_web=True)` — the two new keyword arguments are consumed by Task 6.

- [ ] **Step 1: Move the dashboard and its tests**

```bash
mkdir -p src/packages/web/helpmate_web/static src/packages/web/tests
git mv web/index.html web/css web/js web/vendor src/packages/web/helpmate_web/static/
rmdir web
git mv tests/js src/packages/web/tests/js
git mv tests/ui src/packages/web/tests/ui
```

- [ ] **Step 2: Repoint the two .gitignore negations**

This rule has excluded deliverables twice already. In `.gitignore`, replace the two negation lines:

```
# The dashboard's js/lib holds source (URL-state, export, FEN and stats
# helpers), not a Python build artifact -- exempt it from the generic lib/
# rule above. Same for cm-chessboard's vendored lib/.
!src/packages/web/helpmate_web/static/js/lib/
!src/packages/web/helpmate_web/static/vendor/cm-chessboard/lib/
```

Verify against the index, not the working tree:

```bash
git ls-files src/packages/web/helpmate_web/static/js/lib | wc -l
git ls-files src/packages/web/helpmate_web/static/vendor/cm-chessboard/lib | wc -l
```

Expected: `5` and `2`. **A zero here means a fresh clone would serve a dashboard whose board never loads.**

- [ ] **Step 3: Write the package**

Create `src/packages/web/helpmate_web/__init__.py`:

```python
"""The helpmate dashboard, packaged so the API can find it by import.

The files themselves are plain HTML/CSS/ES modules with no build step; this
package exists only to give them an importable, layout-independent address.
"""
from pathlib import Path

__version__ = "0.7.1"


def static_dir() -> Path:
    """Directory holding index.html, css/, js/ and vendor/.

    Deliberately __file__-relative rather than importlib.resources: the caller
    mounts this as a directory on a live server, which needs a real filesystem
    path, and wheels install unzipped.
    """
    return Path(__file__).resolve().parent / "static"
```

Create `src/packages/web/pyproject.toml`:

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "helpmate-web"
version = "0.7.1"
description = "Web dashboard for helpmate tablebases (static files)"
requires-python = ">=3.9"
license = {text = "MIT"}

[project.optional-dependencies]
dev = ["pytest", "playwright"]

[tool.hatch.build.targets.wheel]
packages = ["helpmate_web"]

# Hatchling honours .gitignore by default, and the repo's generic Python
# `lib/` rule would otherwise drop js/lib and cm-chessboard/lib from the
# wheel -- the negations in .gitignore are what keep them in. Verified by the
# wheel-content check in the plan; do not set ignore-vcs without re-checking.
```

- [ ] **Step 4: Fix the JS tests' relative imports**

In `src/packages/web/tests/js/`, the four files importing from the old tree change `../../web/js/lib/` to `../../helpmate_web/static/js/lib/`:

```bash
sed -i 's#\.\./\.\./web/js/lib/#../../helpmate_web/static/js/lib/#' src/packages/web/tests/js/*.test.js
grep -h "from \"" src/packages/web/tests/js/*.test.js | grep lib
```

Expected: every path reads `../../helpmate_web/static/js/lib/<name>.js`. Note `api.test.js` imports `../../helpmate_web/static/js/api.js` (not under `lib/`) — check it too.

In `Makefile`, `jstest` becomes:

```make
jstest:
	node --test src/packages/web/tests/js/*.test.js
```

- [ ] **Step 5: Teach create_app to locate the dashboard by import**

In `server/helpmate_server/app.py`, replace the static-mount block at the end of `create_app` with:

```python
    # Dashboard. Mounted last so /v1 routes keep priority; html=True serves
    # index.html for "/".
    root = _resolve_web_root(web_root) if serve_web else None
    if root is not None:
        app.mount("/", StaticFiles(directory=str(root), html=True), name="web")
```

and change the signature:

```python
def create_app(chain: ChainSource, mine_cap: int = 1000,
               mine_timeout: float = 30.0, web_root: str | None = None,
               serve_web: bool = True) -> FastAPI:
```

Add above `create_app`:

```python
def _resolve_web_root(explicit: str | None) -> Optional[Path]:
    """Where the dashboard's static files live, or None to serve no dashboard.

    Order: an explicit --web-root (a hard error if wrong, because the user
    named it), then the installed helpmate-web package, then the source
    checkout. Locating it by import means a wheel, an editable install and a
    container all answer the same way -- the previous version guessed between
    two filesystem layouts and silently served nothing when it guessed wrong.
    """
    if explicit is not None:
        p = Path(explicit)
        if not p.is_dir():
            raise ValueError(f"--web-root is not a directory: {p}")
        return p
    try:
        import helpmate_web
        packaged = helpmate_web.static_dir()
        if packaged.is_dir():
            return packaged
    except ImportError:
        pass
    checkout = (Path(__file__).resolve().parents[2]
                / "src" / "packages" / "web" / "helpmate_web" / "static")
    return checkout if checkout.is_dir() else None
```

Note the checkout path is written for `app.py`'s **current** location
(`server/helpmate_server/app.py`, so `parents[2]` is the repo root). Task 6
moves the file and updates this to the package layout.

- [ ] **Step 6: Verify**

```bash
CC=gcc-13 CXX=g++-13 taskset -c 0-3 python3 -m pip install -e ./src/packages/web -q
taskset -c 0-3 node --test src/packages/web/tests/js/*.test.js 2>&1 | tail -5
taskset -c 0-3 python3 -m pytest tests/server -q | tail -3
taskset -c 0-3 python3 -m pytest src/packages/web/tests/ui -q | tail -3
```

Expected: 29 node tests pass; the server suite (including `test_static.py`) passes; 11 browser tests pass.

Confirm the wheel actually carries the two `lib/` directories:

```bash
taskset -c 0-3 python3 -m pip wheel ./src/packages/web -w /tmp/wcheck -q --no-deps
python3 -c "
import zipfile,glob
z=zipfile.ZipFile(glob.glob('/tmp/wcheck/helpmate_web-*.whl')[0])
n=z.namelist()
print('js/lib   :',sum('static/js/lib/' in x for x in n))
print('cm lib   :',sum('cm-chessboard/lib/' in x for x in n))
print('index    :',any(x.endswith('static/index.html') for x in n))"
```

Expected: `5`, `2`, `True`.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat: helpmate-web is its own distribution

The dashboard becomes package data under helpmate_web, and the API locates it
through helpmate_web.static_dir() instead of guessing between two filesystem
layouts. The generic Python lib/ gitignore rule needed its two negations
repointed, or a fresh clone would ship a dashboard whose board never loads.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Create the `helpmate-api` distribution

**Files:**
- Move: `server/helpmate_server/` → `src/packages/api/helpmate_server/`
- Move: `tests/server/` → `src/packages/api/tests/`
- Create: `src/packages/api/pyproject.toml`
- Modify: `src/packages/api/helpmate_server/app.py` (checkout path depth)
- Modify: `src/packages/api/helpmate_server/main.py` (`--web-root`, `--no-web`)

**Interfaces:**
- Consumes: `create_app(..., web_root=None, serve_web=True)` from Task 5.
- Produces: the `helpmate-api` distribution with console scripts `helpmate-server` and `helpmate-tables`.

- [ ] **Step 1: Move the package and its tests**

```bash
mkdir -p src/packages/api
git mv server/helpmate_server src/packages/api/helpmate_server && rmdir server
git mv tests/server src/packages/api/tests
```

- [ ] **Step 2: Fix the checkout-fallback depth**

`app.py` now sits at `src/packages/api/helpmate_server/app.py`, so `parents[2]` is `src/packages/`. In `_resolve_web_root`, replace the `checkout = ...` assignment with:

```python
    # parents[2] is src/packages/ -- app.py lives at
    # src/packages/api/helpmate_server/app.py in a source checkout.
    checkout = Path(__file__).resolve().parents[2] / "web" / "helpmate_web" / "static"
```

- [ ] **Step 3: Write the pyproject**

Create `src/packages/api/pyproject.toml`:

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "helpmate-api"
version = "0.7.1"
description = "Read-only HTTP API for helpmate tablebases"
requires-python = ">=3.9"
license = {text = "MIT"}
dependencies = [
  # A compatible range, not an exact pin, so a patch to one distribution does
  # not force a reinstall of the other. Nothing is on PyPI yet, so `helpmate`
  # must already be installed from this tree before this package -- see the
  # `install` target in the Makefile.
  "helpmate>=0.7.1,<0.8",
  "fastapi>=0.110",
  "uvicorn>=0.29",
  "huggingface_hub>=0.23",
]

[project.optional-dependencies]
dev = ["pytest", "httpx"]

[project.scripts]
helpmate-server = "helpmate_server.main:main"
helpmate-tables = "helpmate_server.tables_cli:main"

[tool.hatch.build.targets.wheel]
packages = ["helpmate_server"]
```

- [ ] **Step 4: Write the failing test for the new flags**

Append to `src/packages/api/tests/test_static.py`:

```python
import pytest
from fastapi.testclient import TestClient
from helpmate_server.app import create_app, _resolve_web_root
from helpmate_server.storage import ChainSource, LocalDir


# conftest.py provides `kqvk_dir` (a session-scoped Path holding a generated
# KQvk closure) and `client`; these cases need their own app, so they build
# one from kqvk_dir the same way the `client` fixture does.
def test_no_web_serves_no_dashboard(kqvk_dir):
    app = create_app(ChainSource([LocalDir(kqvk_dir)]), serve_web=False)
    c = TestClient(app)
    assert c.get("/").status_code == 404
    assert c.get("/v1/health").status_code == 200


def test_explicit_web_root_wins(tmp_path):
    (tmp_path / "index.html").write_text("<p>custom</p>")
    assert _resolve_web_root(str(tmp_path)) == tmp_path


def test_explicit_web_root_that_is_not_a_directory_is_an_error(tmp_path):
    with pytest.raises(ValueError, match="not a directory"):
        _resolve_web_root(str(tmp_path / "nope"))


def test_the_packaged_dashboard_is_found_by_import():
    helpmate_web = pytest.importorskip("helpmate_web")
    assert _resolve_web_root(None) == helpmate_web.static_dir()
```

`test_static.py` currently has no imports at all — it uses only the `client`
fixture — so add the four import lines above at the top of the file.

- [ ] **Step 5: Run it to verify it fails**

Run: `taskset -c 0-3 python3 -m pytest src/packages/api/tests/test_static.py -v`
Expected: FAIL — `create_app() got an unexpected keyword argument 'serve_web'` if Task 5's signature change did not land, otherwise the two `--web-root` cases fail on the import path.

- [ ] **Step 6: Add the CLI flags**

In `main.py`, add to the parser:

```python
    p.add_argument("--web-root", default=None, metavar="DIR",
                   help="serve the dashboard from DIR instead of the installed helpmate-web")
    p.add_argument("--no-web", action="store_true",
                   help="serve the API only, with no dashboard")
```

and change the final line to:

```python
    try:
        app = create_app(chain, a.mine_cap, a.mine_timeout,
                         web_root=a.web_root, serve_web=not a.no_web)
    except ValueError as e:
        p.error(str(e))
    _run(app, a.host, a.port)
```

- [ ] **Step 7: Install and verify**

```bash
CC=gcc-13 CXX=g++-13 taskset -c 0-3 python3 -m pip install -e ./src/packages/api -q
taskset -c 0-3 python3 -m pytest src/packages/api/tests src/packages/bindings/tests tests/repo -q | tail -3
taskset -c 0-3 python3 -m pytest src/packages/web/tests/ui -q | tail -3
```

Expected: all pass, and `tests/repo` no longer skips the api and web `pyproject.toml` parametrisations.

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "feat: helpmate-api is its own distribution

helpmate_server moves under src/packages/api with its own pyproject and its
own tests, and gains --web-root and --no-web so the dashboard's location is
something you can state rather than something the server has to infer.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: Makefile, CI and documentation

**Files:**
- Modify: `Makefile`
- Modify: `.github/workflows/ci.yml`
- Modify: `README.md`, `docs/BUILD.md`, `docs/USAGE.md`, `docs/ROADMAP.md`
- Modify: `CHANGELOG.md`
- Modify: `tools/api_smoke.py` (only if it references moved paths)

**Interfaces:**
- Consumes: every package from Tasks 1–6.
- Produces: `make install`, `make test-core`, `make test-cli`, `make test-api`, `make test-web`, `make test-all`.

- [ ] **Step 1: Add the Makefile targets**

Add to `.PHONY` and to the file:

```make
# Install all three distributions from this tree, in dependency order:
# helpmate-api requires helpmate, and nothing is on PyPI yet, so installing
# them out of order sends pip looking for the name upstream.
install:
	python -m pip install .
	python -m pip install ./src/packages/api ./src/packages/web

test-core: build
	$(BUILD)/helpmate_tests "~[slow]"
test-cli: build
	ctest --test-dir $(BUILD) --output-on-failure -R "^cli_"
test-api:
	python -m pytest src/packages/api/tests -v
test-web: jstest
	python -m pytest src/packages/web/tests/ui -v
test-bindings:
	python -m pytest src/packages/bindings/tests -v
test-repo:
	python -m pytest tests/repo -v
test-all: test test-api test-web test-bindings test-repo
```

- [ ] **Step 2: Update the coverage filter**

In the `coverage` target, `--filter 'src/'` still matches (everything moved deeper under `src/`), but it now also sweeps in the C++ test files under `src/core/tests`. Narrow it:

```make
	gcovr --root . --filter 'src/core/' --filter 'src/packages/cli/' \
	  --exclude '.*/tests/.*' --exclude '.*_deps.*' \
```

- [ ] **Step 3: Update CI**

In `.github/workflows/ci.yml`:
- `cpp` job: unchanged except the FetchContent cache key, which hashes `CMakeLists.txt` — add the new per-package files so a change to any of them busts the cache:
  ```yaml
  key: fetchcontent-${{ runner.os }}-${{ hashFiles('CMakeLists.txt', 'src/**/CMakeLists.txt') }}
  ```
- `python` job: replace `python -m pip install .[dev,server]` with
  ```yaml
      - name: Install all three distributions
        run: |
          python -m pip install .[dev]
          python -m pip install './src/packages/api[dev]' './src/packages/web[dev]'
  ```
  and the test step with
  ```yaml
      - name: Run Python tests
        run: python -m pytest src/packages/bindings/tests src/packages/api/tests tests/repo -v
  ```
- `ui` job: the same install block, then `make jstest`, then
  `python -m pytest src/packages/web/tests/ui -v`. The Playwright cache key
  hashes `pyproject.toml`; point it at `src/packages/web/pyproject.toml`.

- [ ] **Step 4: Sweep the docs**

Find every stale path and command:

```bash
grep -rn 'pip install "\?\.\[server\]\|tests/cpp\|tests/js\|tests/ui\|tests/python\|tests/server\|python/helpmate\|server/helpmate_server\|(^\|[^/]\)web/' \
  README.md docs/*.md tools/*.py | grep -v '^docs/superpowers/'
```

Update each hit. The substantive edits:
- README "Build" and "Install" sections: `make install` or the three-path
  `pip install`, and the fact that `pip install .` now gives you the `helpmate`
  command directly — this is the answer to the build trouble documented in
  "Step-by-step build (if `make test` gives you trouble)".
- `docs/BUILD.md`: the pre-seeded `_deps` workflow's `SKBUILD_CMAKE_ARGS`
  block still applies; add the new package layout and the per-package `make`
  targets.
- `docs/USAGE.md`: the "Install" line under both "Web dashboard" and
  "API server" becomes the three-distribution form; mention `--web-root` and
  `--no-web`.
- Do **not** rewrite paths inside `docs/superpowers/` — those are dated
  records of what was true when written.

- [ ] **Step 5: Add the CHANGELOG entry**

Add above the `[0.7.0]` section:

```markdown
## [0.7.1] - 2026-08-01

### Changed

- **The repo is now three separately installable distributions.**
  `helpmate` (C++ core, the `helpmate` CLI binary, and the Python bindings),
  `helpmate-api` (the FastAPI service and `helpmate-tables`), and
  `helpmate-web` (the dashboard). Each has its own `pyproject.toml` or
  `CMakeLists.txt` and owns its own test suite under
  `src/packages/<name>/tests/`. `make install` installs all three in
  dependency order.
- **`pip install helpmate` now puts the `helpmate` command on PATH.** The
  wheel carries the compiled binary, so using the CLI no longer requires a
  C++ toolchain on the target machine.
- **The API locates the dashboard by importing `helpmate_web`**, with
  `--web-root DIR` to override and `--no-web` to serve the API alone. The
  previous version guessed between two filesystem layouts and served nothing
  when it guessed wrong.
- **One `VERSION` file** feeds CMake, `version.h` and the `cli_version` test
  regex; a repo-level test asserts the three `pyproject.toml` literals,
  `helpmate.__version__`, `helpmate_server.__version__` and
  `helpmate --version` all agree with it.

### Migration

`pip install ".[server]"` no longer exists — the server is a different
distribution. Use `make install`, or
`pip install . ./src/packages/api ./src/packages/web` **in that order**
(`helpmate-api` requires `helpmate`, and nothing is published to PyPI yet).
```

- [ ] **Step 6: Full verification**

Every suite, from a clean configure:

```bash
taskset -c 0-3 cmake -S . -B build && taskset -c 0-3 cmake --build build -j4
taskset -c 0-3 ctest --test-dir build --output-on-failure | tail -3
taskset -c 0-3 ./build/helpmate_tests "~[slow]" | tail -2
taskset -c 0-3 make jstest 2>&1 | tail -5
taskset -c 0-3 python3 -m pytest src/packages/bindings/tests src/packages/api/tests \
    src/packages/web/tests/ui tests/repo -q | tail -3
```

Expected: 117/117 ctest; 86 C++ cases; 29 node tests; the Python total is 75 + 11 browser + the new version and web-root tests.

Then the clean-venv install matrix, which is what "separately deployable" means:

```bash
V="$(mktemp -d)/venv"; python3 -m venv "$V"
CC=gcc-13 CXX=g++-13 taskset -c 0-3 "$V/bin/pip" install . -q
"$V/bin/helpmate" --version                       # helpmate 0.7.1

taskset -c 0-3 "$V/bin/pip" install ./src/packages/api -q
TT="$(mktemp -d)"; taskset -c 0-3 "$V/bin/helpmate" gen KQvk --tables "$TT"
"$V/bin/helpmate-server" --tables "$TT" --port 8799 &
sleep 5
curl -s localhost:8799/v1/health                  # {"status":"ok",...}
curl -s -o /dev/null -w '%{http_code}\n' localhost:8799/   # 404 -- no dashboard yet
kill %1

taskset -c 0-3 "$V/bin/pip" install ./src/packages/web -q
"$V/bin/helpmate-server" --tables "$TT" --port 8799 &
sleep 5
curl -s localhost:8799/ | grep -c 'id="board"'    # 1 -- dashboard now served
kill %1
```

Expected: exactly as annotated. Step 3 proves the dashboard is found through
the installed package and not through a source-tree path — the venv has no
access to the checkout.

- [ ] **Step 7: Commit, merge and push**

```bash
git add -A
git commit -m "docs: package layout, per-package make targets, CI and changelog

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"

git checkout main && git merge --no-ff v0.7.1-packages
GIT_CONFIG_GLOBAL=/dev/null git -c credential.helper='!/usr/bin/gh auth git-credential' \
  push https://github.com/osick/8pieces-helpmate.git main
```

No tag and no GitHub release for this version.

---

## Whole-plan verification checklist

- `ctest --test-dir build -N | grep -c "Test *#"` reports **117**, and `-R "^cli_"` reports **31**.
- `./build/helpmate_tests "~[slow]"` reports **86 test cases**.
- `node --test src/packages/web/tests/js/*.test.js` reports **29 pass, 0 fail**.
- The Python suites pass from `src/packages/{bindings,api}/tests` and `src/packages/web/tests/ui`.
- `git ls-files` finds the five `static/js/lib/*.js` files and the two `cm-chessboard/lib/*.js` files.
- The built `helpmate-web` wheel contains both `lib/` directories and `static/index.html`.
- In a clean venv: `pip install .` gives a working `helpmate` command; adding `./src/packages/api` gives a server that answers `/v1/health` and 404s on `/`; adding `./src/packages/web` makes `/` serve the dashboard.
- `helpmate --version`, `helpmate.__version__`, `helpmate_server.__version__`, the three `pyproject.toml` files and `VERSION` all read `0.7.1`.
- No file outside `docs/superpowers/` still references `python/helpmate`, `server/helpmate_server`, `tests/cpp`, `tests/js`, `tests/ui`, `tests/python`, `tests/server`, or a top-level `web/`.
