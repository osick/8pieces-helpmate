# Test-support script (not installed): asserts a helpmate invocation's exit
# code AND its output TOGETHER. Neither ctest primitive alone can pin both:
# WILL_FAIL only means "nonzero exit" (a segfault passes it too), and
# PASS_REGULAR_EXPRESSION ignores the exit code entirely (see the comment on
# cli_compact_mismatch in CMakeLists.txt). A test that only wants "exits
# nonzero and the message contains X" needs both checked at once, or it can't
# tell "failed correctly" from "failed some other way but the words matched".
#
# Required: -DHELPMATE=<path to the helpmate binary>
#           -DARGS="<space-separated argv, e.g. \"mine KQvk --dtm 2\">"
#           -DEXPECTED_RC=<int>
#           -DPATTERN1=<regex, must be found in combined stdout+stderr>
# Optional: -DPATTERN2=<regex, a second pattern that must also be found>
foreach(v HELPMATE ARGS EXPECTED_RC PATTERN1)
  if(NOT DEFINED ${v})
    message(FATAL_ERROR "assert_exit_and_output.cmake: -D${v}=... is required")
  endif()
endforeach()

separate_arguments(ARGS_LIST UNIX_COMMAND "${ARGS}")
execute_process(COMMAND "${HELPMATE}" ${ARGS_LIST}
                 OUTPUT_VARIABLE out ERROR_VARIABLE err RESULT_VARIABLE rc)
set(combined "${out}${err}")

if(NOT rc EQUAL EXPECTED_RC)
  message(FATAL_ERROR "expected exit code ${EXPECTED_RC}, got ${rc}. Output:\n${combined}")
endif()
if(NOT combined MATCHES "${PATTERN1}")
  message(FATAL_ERROR "output did not match PATTERN1 '${PATTERN1}'. Output:\n${combined}")
endif()
if(DEFINED PATTERN2 AND NOT combined MATCHES "${PATTERN2}")
  message(FATAL_ERROR "output did not match PATTERN2 '${PATTERN2}'. Output:\n${combined}")
endif()

message(STATUS "exit code ${rc} and pattern(s) verified for: ${ARGS}")
