# Test-support script (not installed): fails if ABSENT_PATH exists. Used by
# cli_compact_mismatch_no_sidecar in CMakeLists.txt to assert that `helpmate
# compact` did not write a sidecar for a table whose filename and header
# material disagree (it must refuse the whole file, not partially touch it).
if(NOT DEFINED ABSENT_PATH)
  message(FATAL_ERROR "assert_absent.cmake: -DABSENT_PATH=<path> is required")
endif()
if(EXISTS "${ABSENT_PATH}")
  message(FATAL_ERROR "expected '${ABSENT_PATH}' to be absent, but it exists")
endif()
