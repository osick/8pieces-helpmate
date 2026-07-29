#!/bin/bash
# Task 21 stress harness: the only configuration that has ever reproduced the KNvkqr
# root-slice crash ("error: map::at" / SIGSEGV inside malloc).
#
# WHY THIS IS A SCRIPT AND NOT A ctest CASE
# -----------------------------------------
# The fault is a Heisenbug: every way of observing it hides it. During the Task 21
# investigation it survived, with no report, under all of
#   * gdb (ptrace overhead),
#   * ASan (4 runs, 15-50 min), TSan (zero race reports),
#   * -D_GLIBCXX_ASSERTIONS (>25 min, no assertion),
#   * any rebuild of generator.cpp with extra instrumentation, even at identical -O3 flags,
#   * threads<=4 on an otherwise idle machine (8.7 min clean),
#   * threads=1 (72 min clean).
# What DID reproduce it was scheduling pressure: many more worker threads than available
# CPUs, i.e. constant preemption inside the scan-pass hot loop. That needs `taskset`, which
# ctest cannot express (and a ctest case cannot portably pin cores or size itself to the
# host). It also needs several minutes per iteration and is intermittent, so it belongs in a
# nightly/manual lane, not in `make test`.
#
# USAGE
#   tests/stress_oversubscribed_gen.sh <tables-dir-with-cached-sub-slices> [iterations] [cpus]
# The tables dir must already contain the 7 KNvkqr sub-slices (Kvk, Kvkq, Kvkr, KNvk,
# KNvkq, KNvkr, Kvkqr) so each iteration goes straight to the 121 M-cell root slice; the
# script removes only KNvkqr.hm between iterations.
#
# IMPORTANT: run this against a STOCK Release build (`cmake -DCMAKE_BUILD_TYPE=Release`).
# Do not wrap it in a debugger or sanitizer and do not add instrumentation to the generator
# for the run -- each of those has been observed to mask the fault, so a green run under any
# of them proves nothing.
set -u

TABLES=${1:?usage: $0 <tables-dir> [iterations] [cpus]}
ITERS=${2:-5}
CPUS=${3:-0-3}
ROOT=$(cd "$(dirname "$0")/.." && pwd)
BIN=$ROOT/build/helpmate
# 4x the CPU count: enough preemption to reopen the window, still only `CPUS` worth of load.
THREADS=${THREADS:-16}

[ -x "$BIN" ] || { echo "no Release binary at $BIN -- build it first"; exit 2; }
command -v taskset >/dev/null || { echo "taskset not available"; exit 2; }
for m in Kvk Kvkq Kvkr KNvk KNvkq KNvkr Kvkqr; do
  [ -f "$TABLES/$m.hm" ] || { echo "missing cached sub-slice $TABLES/$m.hm"; exit 2; }
done

echo "stress: $ITERS iteration(s), $THREADS threads pinned to CPUs $CPUS, binary $BIN"
fails=0
for i in $(seq 1 "$ITERS"); do
  rm -f "$TABLES/KNvkqr.hm" "$TABLES/KNvkqr.stats.json"
  t0=$SECONDS
  out=$(taskset -c "$CPUS" "$BIN" gen KNvkqr --tables "$TABLES" --threads "$THREADS" 2>&1)
  rc=$?
  secs=$((SECONDS - t0))
  if [ $rc -ne 0 ]; then
    fails=$((fails + 1))
    echo "iter $i: FAIL rc=$rc after ${secs}s"
    # rc 139 = SIGSEGV (the original silent crash); "map::at" was the user-visible variant.
    echo "$out" | tail -5 | sed 's/^/    /'
  else
    echo "iter $i: ok (${secs}s)"
  fi
done
echo "stress: $fails/$ITERS iterations failed"
[ $fails -eq 0 ] || exit 1
