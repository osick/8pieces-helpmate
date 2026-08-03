# Test-support script (not installed): proves `mine --theme` actually filters,
# not just that it prints SOME line matching "b - - 0 1" (every mined FEN
# matches that -- a PASS_REGULAR_EXPRESSION on it alone would pass even if
# --theme were silently ignored entirely, which is exactly the Critical-2
# defect this whole task fixes: `mine --themes mirror` used to run to
# completion with the filter discarded). Instead this pins the exact,
# independently-verified totals for KQvk dtm=2: 580 positions unfiltered, 477
# with `mirror` (see the "mine filters by theme" comment in
# test_solutions.cpp for how these numbers were measured) -- a filter that
# does nothing would give 580 == 580, not 477 < 580.
#
# Required: -DHELPMATE=<path> -DTABLES=<dir with a generated KQvk table>
foreach(v HELPMATE TABLES)
  if(NOT DEFINED ${v})
    message(FATAL_ERROR "verify_mine_theme_filters.cmake: -D${v}=... is required")
  endif()
endforeach()

execute_process(COMMAND "${HELPMATE}" mine KQvk --dtm 2 --max 100000 --tables "${TABLES}"
                 OUTPUT_VARIABLE out_all RESULT_VARIABLE rc_all)
if(NOT rc_all EQUAL 0)
  message(FATAL_ERROR "unfiltered mine failed with ${rc_all}: ${out_all}")
endif()

execute_process(COMMAND "${HELPMATE}" mine KQvk --dtm 2 --theme mirror --max 100000 --tables "${TABLES}"
                 OUTPUT_VARIABLE out_mirror RESULT_VARIABLE rc_mirror)
if(NOT rc_mirror EQUAL 0)
  message(FATAL_ERROR "--theme mirror mine failed with ${rc_mirror}: ${out_mirror}")
endif()

string(REGEX MATCHALL "\n" all_newlines "${out_all}")
string(REGEX MATCHALL "\n" mirror_newlines "${out_mirror}")
list(LENGTH all_newlines n_all)
list(LENGTH mirror_newlines n_mirror)

if(NOT n_all EQUAL 580)
  message(FATAL_ERROR "expected 580 unfiltered dtm=2 positions for KQvk, got ${n_all}")
endif()
if(NOT n_mirror EQUAL 477)
  message(FATAL_ERROR "expected 477 dtm=2 positions with theme mirror for KQvk, got ${n_mirror}"
                       " (a filter that does nothing would give 580)")
endif()

message(STATUS "mine --theme mirror filters: ${n_mirror} of ${n_all} (KQvk dtm=2) -- confirmed non-trivial")
