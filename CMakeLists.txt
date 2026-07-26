cmake_minimum_required(VERSION 3.24)
project(helpmate LANGUAGES CXX)
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

set(HELPMATE_SOURCES src/chess/board.cpp src/chess/san.cpp src/indexing/material.cpp src/indexing/kk.cpp src/indexing/slice_index.cpp src/format/table_file.cpp src/generator/oracle.cpp src/generator/generator.cpp src/probe/tablebase.cpp)  # tasks append here
add_library(helpmate_core STATIC ${HELPMATE_SOURCES})
target_include_directories(helpmate_core PUBLIC src)
target_link_libraries(helpmate_core PUBLIC chessmg_core nlohmann_json::nlohmann_json Threads::Threads)
target_compile_options(helpmate_core PRIVATE -O2 -Wall -Wextra)

enable_testing()
add_executable(helpmate_tests tests/cpp/test_sanity.cpp tests/cpp/test_board.cpp tests/cpp/test_san.cpp tests/cpp/test_material.cpp tests/cpp/test_kk.cpp tests/cpp/test_slice_index.cpp tests/cpp/test_table_file.cpp tests/cpp/test_oracle.cpp tests/cpp/test_generator_init.cpp tests/cpp/test_generator_kqvk.cpp tests/cpp/test_generator_pawns.cpp tests/cpp/test_counts.cpp tests/cpp/test_stats.cpp tests/cpp/test_threads.cpp tests/cpp/test_probe.cpp)
target_link_libraries(helpmate_tests PRIVATE helpmate_core Catch2::Catch2WithMain)
list(APPEND CMAKE_MODULE_PATH ${catch2_SOURCE_DIR}/extras)
include(Catch)
catch_discover_tests(helpmate_tests TEST_SPEC "~[slow]")
# Slow tests (full KPvkp closure generation) are excluded from `make test` by default.
# Run them manually with: ./build/helpmate_tests "[slow]"

add_executable(helpmate src/cli/main.cpp)
target_link_libraries(helpmate PRIVATE helpmate_core)

if(HELPMATE_PYTHON)
  find_package(pybind11 CONFIG REQUIRED)
  pybind11_add_module(_helpmate src/bindings/pymodule.cpp)
  target_link_libraries(_helpmate PRIVATE helpmate_core)
  install(TARGETS _helpmate DESTINATION helpmate)
endif()

set(CLI_TT ${CMAKE_BINARY_DIR}/cli_tables)
add_test(NAME cli_gen COMMAND helpmate gen KQvk --tables ${CLI_TT})
add_test(NAME cli_probe COMMAND helpmate probe "8/7k/5K2/8/8/8/8/6Q1 b - - 0 1" --tables ${CLI_TT})
add_test(NAME cli_line COMMAND helpmate line "8/7k/5K2/8/8/8/8/6Q1 b - - 0 1" --tables ${CLI_TT})
add_test(NAME cli_stats COMMAND helpmate stats KQvk --tables ${CLI_TT})
add_test(NAME cli_mine COMMAND helpmate mine KQvk --dtm 2 --count 1 --max 3 --tables ${CLI_TT})
add_test(NAME cli_missing COMMAND helpmate probe "8/8/8/8/3n4/4k3/8/4K3 w - - 0 1" --tables ${CLI_TT})
add_test(NAME cli_badfen COMMAND helpmate probe "garbage" --tables ${CLI_TT})
# review fix round: malformed and out-of-range numeric flags must not crash
# (std::stoi throwing std::invalid_argument/std::out_of_range uncaught ->
# SIGABRT); both must exit 3 with a clear message instead.
add_test(NAME cli_badint_malformed COMMAND helpmate mine KQvk --dtm abc --tables ${CLI_TT})
add_test(NAME cli_badint_range COMMAND helpmate gen KQvk --threads 99999999999999999999 --tables ${CLI_TT})
# review fix round: `line --all` on an already-mated (dtm=0) position must
# give the same "no line to print" message as the non---all branch, not a
# silent blank line (tb.lines() returns one *empty* line here, so a naive
# ls.empty() check misses it).
add_test(NAME cli_line_already_mate COMMAND helpmate line "8/8/8/8/8/8/8/kQK5 b - - 0 1" --tables ${CLI_TT} --all)
# count=4 (not 1): four optimal replies tie at dtm=2 here -- see Task 8's
# corrected golden (test_probe.cpp), reconfirmed by running the built CLI.
set_tests_properties(cli_probe PROPERTIES PASS_REGULAR_EXPRESSION "dtm=2 .*h#1.*count=4" DEPENDS cli_gen)
# legal_moves() ordering deterministically yields Kh6 Qh2# as the first optimal
# line for `line` (no --all); reconfirmed by running the built CLI.
set_tests_properties(cli_line  PROPERTIES PASS_REGULAR_EXPRESSION "Kh6 Qh2#" DEPENDS cli_gen)
set_tests_properties(cli_stats PROPERTIES PASS_REGULAR_EXPRESSION "max_dtm" DEPENDS cli_gen)
set_tests_properties(cli_mine  PROPERTIES PASS_REGULAR_EXPRESSION "b - - 0 1" DEPENDS cli_gen)
set_tests_properties(cli_missing PROPERTIES PASS_REGULAR_EXPRESSION "helpmate gen" DEPENDS cli_gen)
set_tests_properties(cli_badfen PROPERTIES PASS_REGULAR_EXPRESSION "error")
set_tests_properties(cli_badint_malformed PROPERTIES PASS_REGULAR_EXPRESSION "error.*--dtm")
set_tests_properties(cli_badint_range PROPERTIES PASS_REGULAR_EXPRESSION "error.*--threads")
set_tests_properties(cli_line_already_mate PROPERTIES PASS_REGULAR_EXPRESSION "already mate" DEPENDS cli_gen)
