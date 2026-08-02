# Block-compressed tables (v0.7.5) — Design

Date: 2026-08-02
Status: approved by user (brainstorming session 2026-08-02)
Origin: the Backlog's "Compression (conditional: performance first)" rung in
`docs/ROADMAP.md`, promoted to v0.7.5 after the measurements below.
Version: 0.7.5. No GitHub release. Merged and pushed to `main`.

## Why now, and why not the other candidates

The corpus is 89.7 GB across 61 real tables (plus 37 pruned markers), and two
6-piece tables are 31.0 GB each. Four improvements were considered and
measured against that corpus rather than against intuition:

| candidate | measured effect | verdict |
|---|---|---|
| block compression | **11.4–17.9×** | this rung |
| DTM bit-packing | 19% of a file | redundant under compression |
| count/DTM file split | moves 50% of bytes | orthogonal, later |
| combinatorial indexing | **3.5% of the corpus** | not worth a format break |

**Combinatorial indexing was the initial recommendation and the measurement
overturned it.** Syzygy gains heavily from it because doubled pawns and rooks
are ubiquitous there. Helpmate material classes are mostly one-of-each: only
9 of 61 real tables have any repeated piece type, together 6.2 GB of 89.7 GB,
and *both* 31 GB tables (`KBvkqrb` = K,B vs k,q,r,b) have none. Extending it
to falling-factorial indexing over distinct non-king squares would add ~20%
on 6-piece slices, but that is still an index change invalidating every table
on disk for a fifth of what compression gives for free.

Where the bytes actually go, from the stats sidecars:

| | KBvkqrb | KBvkqrn |
|---|---|---|
| plane_size | 7,751,073,792 | 7,751,073,792 |
| solvable | 25.9% | 52.6% |
| unsolvable | 26.1% | 0.6% |
| invalid | 48.0% | 46.9% |
| max_dtm | 17 | 25 |
| bytes per solvable position | 7.7 | 3.8 |

73% of `KBvkqrb` is two constant bytes (`DTM_INVALID`, `DTM_UNSOLVABLE`).
That is what compression exploits, and why it is not merely papering over
waste here: the waste is only expensive when stored raw.

A zero-dependency domain encoding was considered and measured out. Only
**10.5%** of blocks are entirely constant at any block size (16/64/256 KB) —
the invalid cells interleave with real data at fine granularity rather than
clustering — so an all-constant-block scheme would return ~10%, not 10×.

## Measurements that set the parameters

`KBvkqrb`, 128 MB of its `dtm_wtm` plane, each block compressed
**independently** (which is what random access requires — a single stream
would destroy it):

| block | level | ratio | index overhead | decompress one block |
|---|---|---|---|---|
| 16 KB | 1 | 11.4× | 0.049% | 11 µs |
| 16 KB | 3 | 12.6× | 0.049% | 10 µs |
| 64 KB | 1 | 13.5× | 0.012% | 38 µs |
| **64 KB** | **3** | **14.5×** | **0.012%** | **38 µs** |
| 256 KB | 3 | 15.2× | 0.003% | 145 µs |
| 256 KB | 9 | 17.9× | 0.003% | 121 µs |

**Default: 64 KB blocks, zstd level 3.** 16 KB/level 1 is cheaper per probe
but gives up 3.1× of ratio; 256 KB/level 9 gives 3.4× more ratio but 121 µs
per block starts to matter for `mine`'s sequential scan. Both alternatives
are recorded here so a later change is an informed one rather than a fresh
guess.

Cold probe latency should *improve*, not regress: a cold probe costs one
block decompress (38 µs) but reads 14× less from disk. Warm probes are
unchanged — a cached block is a plain memory read.

## Format

Compressed tables are **`version = 3`, `encoding = 2`**.

Using a new `version` as well as the new `encoding` is deliberate. The
current reader validates `encoding == 1` (`table_file.cpp:157`), so an older
binary will not misread a compressed table — but it falls into the generic
failure path and reports "unreadable table". `version > 2` already produces
the correct "written by a newer helpmate … upgrade this build" diagnostic
(`table_file.cpp:147`), so bumping the version costs nothing and gives every
binary already in the wild the right message.

Version semantics become:

- `1` — ordinary table, raw byte planes
- `2` — all-unsolvable marker (no payload)
- `3` — ordinary table, block-compressed planes

Two of the header's 14 reserved bytes are claimed:

```c
uint32_t block_size;   // bytes of UNCOMPRESSED data per block; 65536 default
uint8_t  codec;        // 1 = zstd
uint8_t  reserved[9];
```

Putting `block_size` in the file rather than in the build means the choice
can be retuned later without a version bump, and a reader handles any file it
is given.

Layout:

```
header(64) | json(json_len) | block index | compressed blocks
```

The block index is `uint64 n_blocks` followed by `n_blocks + 1` `uint64`
offsets, each relative to the start of the first compressed block. Block *i*
occupies `[off[i], off[i+1])`, so a block's compressed length needs no
separate field and the final entry gives the total payload size.

The four planes are addressed as **one logical byte range** of
`4 × plane_size`, in the existing order `dtm_wtm, dtm_btm, cnt_wtm, cnt_btm`,
cut into fixed `block_size` chunks. The last block is short and decompresses
to fewer than `block_size` bytes. `get(stm, cell)` maps to a logical offset
exactly as today, then `block = offset / block_size`,
`byte = offset % block_size`.

## Reader

`TableReader` keeps `mmap` for the header, JSON and block index — those stay
cheap and are read directly. It gains:

- a decompressed-block cache, bounded and LRU, default **64 blocks (4 MB)**;
- `get(stm, cell)` becomes cache-lookup-or-decompress-then-insert.

The cache is mutex-guarded. Generation is multi-threaded and probing may be
concurrent, so contention is a real risk; if measurement shows it, the
fallback is a thread-local cache per reader, which trades memory for
lock-freedom. That decision is made from a measurement in the implementation,
not assumed here.

Raw tables (`version 1`/`2`) keep exactly today's code path — a bare `mmap`
byte load with no cache and no branch beyond the encoding check made once at
open time. Nothing about the uncompressed hot path regresses.

## Writer and converter

`TableWriter` gains a compressed path used **at finalize**, after generation
completes, so compression never runs inside the generator's hot loop. Its
cost shows up as wall-clock at the end of a run, which the performance gate
below measures.

`helpmate gen --compress` opts in. **The default stays raw in v0.7.5.** The
default flips in a later version, once the gate's numbers have been seen on
real slices on real hardware rather than on a 128 MB sample.

`helpmate compact --compress <dir>` converts tables already on disk:

- one file at a time, writing `<path>.tmp` and atomically renaming, so an
  interrupted conversion never leaves a corrupt table;
- **skips any file modified within the last hour** — a 6-piece generation run
  is active on the development machine and must not be touched;
- skips markers (`version 2`) and already-compressed tables (`version 3`),
  reporting both as no-ops rather than errors;
- refuses, as `compact` already does, any table whose filename disagrees with
  its header material.

## The performance gate

`docs/ROADMAP.md` makes this rung conditional, and that condition stands. It
ships only if, measured against the real binary and a real slice:

1. **ratio ≥ 5×** — measured 14.5×, comfortably clear;
2. **warm probe within ~2× of raw** — expected equal, since a cached block is
   a memory read; must be shown;
3. **generation slows by no more than a few percent** — compression happens
   once at finalize, so this should be small, but it must be shown, not
   assumed.

If (2) or (3) fail, the fallback is the roadmap's own: keep the on-disk
format raw and compress only for transport in `helpmate-tables push/pull`.
That is a good outcome, not a failure.

## Dependency

`libzstd`, as a **hard-required system package**, found at configure time
with a clear error naming what to install:

```
libzstd headers not found -- install libzstd-devel (openSUSE)
or libzstd-dev (Debian/Ubuntu)
```

The development machine has `libzstd.so.1.5.0` but no header, so
`libzstd-devel` must be installed there. CI runners install `libzstd-dev`.

Deliberately **not** a fourth `FetchContent` clone: this machine's gitconfig
rewrites GitHub HTTPS URLs to SSH, which has already hung builds on an
invisible passphrase dialog twice in this project. A configure-time
`find_package` failure is loud and instant; a hung clone is neither.

## Testing

- **Round-trip equality.** Generate a small real closure (`KQvk`), write it
  raw and compressed, and assert that *every* cell read through both readers
  is byte-identical for both `dtm` and `count`, for both sides to move. This
  is the central correctness claim and it is exhaustive at this size.
- **A committed golden compressed fixture**, so the on-disk format cannot
  drift silently. A reader change that breaks it fails loudly.
- **Short final block.** `plane_size × 4` is not a multiple of 64 KB in
  general; a test pins a material whose last block is partial.
- **Cache behaviour.** Reading the same cell twice must decompress once;
  reading more distinct blocks than the cache holds must still return correct
  values.
- **Diagnostics.** A table with an unknown `encoding` or `version` must
  report the "newer helpmate … upgrade this build" message, not "unreadable".
- **CLI.** The existing `cli_compact*` ctest cases extended for `--compress`,
  including the skip-recent-files behaviour and the marker/already-compressed
  no-ops.
- **The gate itself**, from the section above, with real numbers recorded in
  the implementation report.

## Out of scope

DTM bit-packing (redundant under compression); splitting the count planes
into a companion file (orthogonal, and worth doing on its own merits later);
combinatorial or falling-factorial indexing (3.5% for a format break);
anything touching generation RAM — planes stay uncompressed in memory, so the
7-piece ~1.8 TB problem is untouched and remains v0.9's out-of-core work;
flipping the `gen` default to compressed, which is a later version once the
gate has been run at scale.

## Risks

- **Cache contention under multi-threaded generation.** Mitigated by
  measuring, with thread-local caches as the known fallback.
- **A converter bug corrupting the 89.7 GB corpus.** Mitigated by
  write-tmp-then-rename, by never modifying the source file, and by the
  round-trip equality test running before any conversion is offered.
- **The active 6-piece run.** Mitigated by the one-hour skip window, and by
  the converter being opt-in and per-directory rather than automatic.
- **zstd version differences across machines** changing compressed bytes.
  Decompression is version-stable, so this affects only byte-exact
  comparison of two independently written files; the golden fixture therefore
  pins decompressed content, never compressed bytes.
