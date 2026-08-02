# Test-support script (not installed): proves the one-hour skip in
# `helpmate compact --compress` -- see main.cpp's cmd_compact_compress. A long
# generation run may be writing into the target directory right now, and
# rewriting a table mid-write would corrupt it, so the converter must skip
# (not open) any .hm file whose mtime is within the last hour, checked before
# the file is opened at all.
#
# Sequence: write a legacy raw table (mk_legacy_table, instant, no `helpmate
# gen` needed), touch it to "now", run compact --compress and require it
# reports the file as skipped-recent with nothing rewritten; then back-date
# its mtime to two hours ago, run compact --compress again, and require it
# now reports a rewrite AND that the file actually shrank -- proving the skip
# is a real gate, not a no-op that happens to match the regex either way.
#
# Required: -DHELPMATE=<path> -DMK_LEGACY_TABLE=<path> -DDIR=<scratch dir>
foreach(v HELPMATE MK_LEGACY_TABLE DIR)
  if(NOT DEFINED ${v})
    message(FATAL_ERROR "verify_compress_skip_recent.cmake: -D${v}=... is required")
  endif()
endforeach()

file(REMOVE_RECURSE "${DIR}")
file(MAKE_DIRECTORY "${DIR}")
set(TBL "${DIR}/Kvk.hm")

execute_process(COMMAND "${MK_LEGACY_TABLE}" "${TBL}" Kvk RESULT_VARIABLE rc)
if(NOT rc EQUAL 0)
  message(FATAL_ERROR "mk_legacy_table failed with ${rc}")
endif()

# mk_legacy_table just wrote it, so its mtime is already "now"; touch it
# explicitly anyway so the test does not depend on that being true forever.
execute_process(COMMAND touch "${TBL}")

file(SIZE "${TBL}" size_before)

execute_process(COMMAND "${HELPMATE}" compact "${DIR}" --compress
                OUTPUT_VARIABLE out1 RESULT_VARIABLE rc1)
message(STATUS "compact --compress (fresh mtime): ${out1}")
if(NOT rc1 EQUAL 0)
  message(FATAL_ERROR "compact --compress failed with ${rc1} on a fresh table")
endif()
if(NOT out1 MATCHES "1 skipped \\(recently written\\)")
  message(FATAL_ERROR "expected the fresh table to be skipped as recently-written; got: ${out1}")
endif()
if(NOT out1 MATCHES "0 rewritten")
  message(FATAL_ERROR "expected 0 rewritten for a fresh table; got: ${out1}")
endif()

file(SIZE "${TBL}" size_after_skip)
if(NOT size_after_skip EQUAL size_before)
  message(FATAL_ERROR "a skipped (recently-written) table must not change size: "
                       "${size_before} -> ${size_after_skip}")
endif()

# Back-date the mtime past the one-hour cutoff and try again: this time it
# must actually convert.
execute_process(COMMAND touch -d "2 hours ago" "${TBL}")

execute_process(COMMAND "${HELPMATE}" compact "${DIR}" --compress
                OUTPUT_VARIABLE out2 RESULT_VARIABLE rc2)
message(STATUS "compact --compress (2h-old mtime): ${out2}")
if(NOT rc2 EQUAL 0)
  message(FATAL_ERROR "compact --compress failed with ${rc2} on a 2-hour-old table")
endif()
if(NOT out2 MATCHES "1 rewritten")
  message(FATAL_ERROR "expected the 2-hour-old table to be rewritten; got: ${out2}")
endif()

file(SIZE "${TBL}" size_after_convert)
if(NOT size_after_convert LESS size_before)
  message(FATAL_ERROR "a converted table must shrink: ${size_before} -> ${size_after_convert}")
endif()

message(STATUS "one-hour skip verified: fresh mtime skipped (${size_before} bytes unchanged), "
               "2-hour-old mtime converted (${size_before} -> ${size_after_convert} bytes)")
