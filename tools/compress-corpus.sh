#!/usr/bin/env bash
# Compress raw .hm tables from one directory into another, one at a time.
#
#   tools/compress-corpus.sh [-n] [-b KIB] [-j] SRC DST
#
#   -n      dry run: report what would be done, touch nothing
#   -b KIB  block size in KiB (default 64, the measured best; see docs/USAGE.md)
#   -j      also copy the <Material>.stats.json sidecar (default: yes)
#
# Why it works the way it does:
#
#   `helpmate compact --compress DIR` rewrites tables IN PLACE inside DIR. To
#   compress SRC/X.hm into DST without modifying SRC, each table is staged into
#   a scratch directory on DST's filesystem, compressed there, and moved into
#   DST. One table at a time, so peak extra disk is one table plus its output,
#   not the size of the whole corpus.
#
#   `cp -p` preserves mtime deliberately. `compact --compress` refuses any file
#   written in the last hour, because a generation run may still be writing it.
#   A plain `cp` would stamp every staged file with the current time and that
#   guard would skip all of them. Preserving the timestamp keeps the guard
#   meaningful, and this script applies the same one-hour rule to SRC before it
#   even reads a file, so a table being generated right now is never copied
#   mid-write.
#
#   Markers (format version 2, all-unsolvable) have no payload to compress.
#   `compact --compress` reports them as no-ops, so they are copied straight
#   across instead of staged.
#
#   Tables already present in DST are left alone. helpmate's own converter
#   treats an already-compressed table at the same block size as a true no-op
#   precisely to avoid burning a decompress+recompress pass for byte-identical
#   output, so there is nothing to gain by revisiting them.
#
# Safety: SRC is only ever read. Nothing is deleted. The converter writes
# <path>.tmp and atomically renames, and reopens the result to verify it before
# the rename, so an interrupted run cannot leave a corrupt table behind.

set -euo pipefail

# Force the C locale for numeric formatting. Under a comma-decimal locale
# (de_DE and friends) awk still emits "2.0394" while printf %f demands
# "2,0394", so the ratio line fails -- and under `set -e` that failure aborts
# the whole run mid-corpus. Found by running this, not by reading it.
export LC_ALL=C

HELPMATE="${HELPMATE:-./build/helpmate}"
BLOCK_KIB=64
DRY=0
COPY_SIDECAR=1

usage() { sed -n '2,4p' "$0" | sed 's/^# \{0,1\}//'; exit 2; }

while getopts "nb:jh" opt; do
  case "$opt" in
    n) DRY=1 ;;
    b) BLOCK_KIB="$OPTARG" ;;
    j) COPY_SIDECAR=0 ;;
    *) usage ;;
  esac
done
shift $((OPTIND - 1))
[ $# -eq 2 ] || usage

SRC="${1%/}"
DST="${2%/}"

# An `a && b` statement whose last command fails is a non-zero statement, and
# `set -e` kills the script -- so a table that simply has no sidecar must not
# be expressed that way.
copy_sidecar() {
  if [ "$COPY_SIDECAR" = "1" ] && [ -e "$SRC/$1.stats.json" ]; then
    cp -p "$SRC/$1.stats.json" "$DST/$1.stats.json"
  fi
}

[ -d "$SRC" ] || { echo "error: not a directory: $SRC" >&2; exit 3; }
[ -d "$DST" ] || { echo "error: not a directory: $DST" >&2; exit 3; }
[ -x "$HELPMATE" ] || { echo "error: helpmate binary not found or not executable: $HELPMATE" >&2
                        echo "       set HELPMATE=/path/to/helpmate" >&2; exit 3; }
[ "$(realpath "$SRC")" != "$(realpath "$DST")" ] || {
  echo "error: SRC and DST are the same directory; use 'helpmate compact --compress' for in-place" >&2
  exit 3; }

STAGE="$DST/.compress-staging"
mkdir -p "$STAGE"
# A staging dir on DST's own filesystem is what makes the final mv atomic.
if [ "$(stat -f -c %i "$STAGE")" != "$(stat -f -c %i "$DST")" ]; then
  echo "error: staging dir is not on the same filesystem as $DST" >&2; exit 3
fi
cleanup() { rmdir "$STAGE" 2>/dev/null || true; }
trap cleanup EXIT

now=$(date +%s)
n_done=0 n_marker=0 n_present=0 n_recent=0 n_fail=0
bytes_in=0 bytes_out=0

for src in "$SRC"/*.hm; do
  [ -e "$src" ] || { echo "no .hm files in $SRC"; exit 0; }
  stem=$(basename "$src" .hm)
  dst="$DST/$stem.hm"

  if [ -e "$dst" ]; then
    n_present=$((n_present + 1))
    continue
  fi

  # Never read a table that may still be being written.
  mtime=$(stat -c %Y "$src")
  if [ $((now - mtime)) -lt 3600 ]; then
    echo "skip  $stem  (written in the last hour; a generation run may be active)"
    n_recent=$((n_recent + 1))
    continue
  fi

  size_in=$(stat -c %s "$src")

  # version is a uint32 LE at byte offset 4 of the 64-byte header.
  version=$(od -An -tu4 -j4 -N4 "$src" | tr -d ' ')
  if [ "$version" = "2" ]; then
    if [ "$DRY" = "1" ]; then
      echo "would copy      $stem  (marker, no payload)"
    else
      cp -p "$src" "$STAGE/$stem.hm" && mv "$STAGE/$stem.hm" "$dst"
      copy_sidecar "$stem"
      echo "copied marker   $stem"
    fi
    n_marker=$((n_marker + 1))
    continue
  fi

  if [ "$DRY" = "1" ]; then
    printf 'would compress  %-12s %s\n' "$stem" "$(numfmt --to=iec --suffix=B "$size_in")"
    n_done=$((n_done + 1))
    bytes_in=$((bytes_in + size_in))
    continue
  fi

  printf 'compressing     %-12s %s ... ' "$stem" "$(numfmt --to=iec --suffix=B "$size_in")"
  if ! cp -p "$src" "$STAGE/$stem.hm"; then
    echo "FAILED (copy)"; n_fail=$((n_fail + 1)); rm -f "$STAGE/$stem.hm"; continue
  fi
  if ! "$HELPMATE" compact --compress "$STAGE" --block-size "$BLOCK_KIB" >/dev/null; then
    echo "FAILED (compress)"; n_fail=$((n_fail + 1)); rm -f "$STAGE/$stem.hm"; continue
  fi
  size_out=$(stat -c %s "$STAGE/$stem.hm")
  mv "$STAGE/$stem.hm" "$dst"
  copy_sidecar "$stem"
  printf '%s (%.2fx)\n' "$(numfmt --to=iec --suffix=B "$size_out")" \
    "$(awk -v a="$size_in" -v b="$size_out" 'BEGIN{print a/b}')"
  n_done=$((n_done + 1))
  bytes_in=$((bytes_in + size_in))
  bytes_out=$((bytes_out + size_out))
done

echo
if [ "$DRY" = "1" ]; then
  echo "dry run: would compress $n_done table(s), $(numfmt --to=iec --suffix=B "$bytes_in") in"
else
  echo "compressed $n_done, copied $n_marker marker(s), failed $n_fail"
  if [ "$bytes_out" -gt 0 ]; then
    printf 'total %s -> %s (%.2fx)\n' \
      "$(numfmt --to=iec --suffix=B "$bytes_in")" "$(numfmt --to=iec --suffix=B "$bytes_out")" \
      "$(awk -v a="$bytes_in" -v b="$bytes_out" 'BEGIN{print a/b}')"
  fi
fi
echo "already in $DST: $n_present, skipped as too recent: $n_recent"
[ "$n_fail" -eq 0 ]
