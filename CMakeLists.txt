cmake_minimum_required(VERSION 3.24)
project(helpmate VERSION 0.6.1 LANGUAGES CXX)
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

option(HELPMATE_COVERAGE "coverage instrumentation" OFF)
if(HELPMATE_COVERAGE)
  target_compile_options(helpmate_core PRIVATE --coverage -O0 -g)
  target_link_options(helpmate_core PUBLIC --coverage)
endif()

enable_testing()
add_executable(helpmate_tests tests/cpp/test_sanity.cpp tests/cpp/test_board.cpp tests/cpp/test_san.cpp tests/cpp/test_material.cpp tests/cpp/test_kk.cpp tests/cpp/test_slice_index.cpp tests/cpp/test_table_file.cpp tests/cpp/test_oracle.cpp tests/cpp/test_generator_init.cpp tests/cpp/test_generator_kqvk.cpp tests/cpp/test_generator_pawns.cpp tests/cpp/test_counts.cpp tests/cpp/test_stats.cpp tests/cpp/test_threads.cpp tests/cpp/test_probe.cpp tests/cpp/test_generator_lookup_guards.cpp tests/cpp/test_ram_guard.cpp tests/cpp/test_slice_index_6piece.cpp tests/cpp/test_generator_prune.cpp)
target_link_libraries(helpmate_tests PRIVATE helpmate_core Catch2::Catch2WithMain)
list(APPEND CMAKE_MODULE_PATH ${catch2_SOURCE_DIR}/extras)
include(Catch)
catch_discover_tests(helpmate_tests TEST_SPEC "~[slow]")
# Slow tests (full KPvkp closure generation) are excluded from `make test` by default.
# Run them manually with: ./build/helpmate_tests "[slow]"

add_executable(helpmate src/cli/main.cpp)
target_link_libraries(helpmate PRIVATE helpmate_core)
install(TARGETS helpmate RUNTIME DESTINATION bin)

# Test-support only (not installed): writes a legacy-format all-unsolvable
# table so `helpmate compact`'s ctest coverage has a real rewrite target --
# see tests/cpp/mk_legacy_table.cpp for why `helpmate gen` can no longer
# produce this fixture itself.
add_executable(mk_legacy_table tests/cpp/mk_legacy_table.cpp)
target_link_libraries(mk_legacy_table PRIVATE helpmate_core)

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
# v0.5.0: --verbose lifecycle lines go to stderr (ctest matches merged output);
# on a re-run every slice is already on disk, so "cached" must appear.
add_test(NAME cli_gen_verbose COMMAND helpmate gen KQvk --tables ${CLI_TT} --verbose)
add_test(NAME cli_version COMMAND helpmate --version)
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
# v0.6.1: `compact` rewrites all-unsolvable tables already on disk as tiny
# markers. `helpmate gen` itself now prunes every provably-unsolvable slice
# to a marker at generation time (see generator.cpp's opt.prune path), so
# gen's own output never gives compact anything left to do -- compact exists
# for tables written by OLDER binaries, before that pruning feature existed.
# mk_legacy_table fabricates exactly that: an ordinary (version 1) table,
# fully populated, whose every cell happens to read DTM_UNSOLVABLE.
set(COMPACT_TT ${CMAKE_BINARY_DIR}/compact_tables)
add_test(NAME cli_compact_fixture_mkdir COMMAND ${CMAKE_COMMAND} -E make_directory ${COMPACT_TT})
add_test(NAME cli_compact_fixture_write COMMAND mk_legacy_table ${COMPACT_TT}/Kvk.hm Kvk)
add_test(NAME cli_compact_dry COMMAND helpmate compact ${COMPACT_TT} --dry-run)
add_test(NAME cli_compact COMMAND helpmate compact ${COMPACT_TT})
# Final-review fix: compact must refuse (not touch) a table whose FILE NAME and
# header material disagree, rather than deriving the sidecar path from the
# (untrusted) header name. Fabricate exactly that: a legitimate legacy table
# for material Kvk, renamed to KQvk.hm so its filename no longer matches its
# own header.
set(COMPACT_MISMATCH_TT ${CMAKE_BINARY_DIR}/compact_mismatch_tables)
add_test(NAME cli_compact_mismatch_fixture_mkdir COMMAND ${CMAKE_COMMAND} -E make_directory ${COMPACT_MISMATCH_TT})
add_test(NAME cli_compact_mismatch_fixture_write COMMAND mk_legacy_table ${COMPACT_MISMATCH_TT}/Kvk.hm Kvk)
add_test(NAME cli_compact_mismatch_fixture_rename COMMAND ${CMAKE_COMMAND} -E rename ${COMPACT_MISMATCH_TT}/Kvk.hm ${COMPACT_MISMATCH_TT}/KQvk.hm)
add_test(NAME cli_compact_mismatch COMMAND helpmate compact ${COMPACT_MISMATCH_TT})
add_test(NAME cli_compact_mismatch_no_sidecar COMMAND ${CMAKE_COMMAND}
         -DABSENT_PATH=${COMPACT_MISMATCH_TT}/KQvk.stats.json
         -P ${CMAKE_SOURCE_DIR}/tests/cpp/assert_absent.cmake)
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
set_tests_properties(cli_gen_verbose PROPERTIES PASS_REGULAR_EXPRESSION "cached" DEPENDS cli_gen)
set_tests_properties(cli_version PROPERTIES PASS_REGULAR_EXPRESSION "helpmate 0\\.6\\.1")
set_tests_properties(cli_badint_malformed PROPERTIES PASS_REGULAR_EXPRESSION "error.*--dtm")
set_tests_properties(cli_badint_range PROPERTIES PASS_REGULAR_EXPRESSION "error.*--threads")
set_tests_properties(cli_line_already_mate PROPERTIES PASS_REGULAR_EXPRESSION "already mate" DEPENDS cli_gen)
set_tests_properties(cli_compact_fixture_write PROPERTIES DEPENDS cli_compact_fixture_mkdir)
set_tests_properties(cli_compact_dry PROPERTIES PASS_REGULAR_EXPRESSION "would rewrite" DEPENDS cli_compact_fixture_write)
set_tests_properties(cli_compact PROPERTIES PASS_REGULAR_EXPRESSION "rewrote|already compact" DEPENDS cli_compact_dry)
set_tests_properties(cli_compact_mismatch_fixture_write PROPERTIES DEPENDS cli_compact_mismatch_fixture_mkdir)
set_tests_properties(cli_compact_mismatch_fixture_rename PROPERTIES DEPENDS cli_compact_mismatch_fixture_write)
# helpmate compact exits 3 on a name/header mismatch (verified manually: `helpmate
# compact <dir>; echo $?` -> 3); PASS_REGULAR_EXPRESSION below additionally pins the
# error message (ignores exit code, hence the manual note -- same idiom as cli_badfen).
set_tests_properties(cli_compact_mismatch PROPERTIES
    PASS_REGULAR_EXPRESSION "error:.*is for material 'Kvk'.*expected 'KQvk'"
    DEPENDS cli_compact_mismatch_fixture_rename)
set_tests_properties(cli_compact_mismatch_no_sidecar PROPERTIES DEPENDS cli_compact_mismatch)
