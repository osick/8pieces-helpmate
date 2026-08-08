# Query acceleration — Design

Date: 2026-08-08
Status: **Layer 0 approved for implementation. Layers 1 and 2 are designed but
explicitly conditional on Layer 0's measurements.**
Origin: brainstorming session of 2026-08-08, opened by the user's proposal of a
database layer (`helpmate gen --todb`, `helpmate mine --config`) with
performance as the stated primary motivation.

Supersedes nothing. Complements
`2026-08-04-query-surface-concept.md` (which named live result counts as its
hard unsolved problem — Layer 1 solves it for two of the dimensions) and
`2026-08-07-format-v4-recommendation.md` (which measured where the bytes go).

## The question that was asked

Should a database back the tablebase, so that `mine` stops scanning?

## The answer, and the evidence for it

**No database should hold the cell array.** Not SQLite, DuckDB, Parquet,
RocksDB, LMDB, ClickHouse or chDB. This is not a preference; three independent
research passes and two measurement passes reached it separately.

The root cause is one sentence: **the key is already the array offset.** A
position's cell index is computed arithmetically from the position
(`SliceIndex::encode`), so there is nothing to look up. Every engine surveyed
must *store* that key and charges 16–19 bytes of per-row structure for a 4-byte
row:

| engine | per-row cost | one 6-piece material | disqualifier |
|---|---|---|---|
| SQLite | 17 B for 4 B | ~132 GB (vs 3.3 GB today) | Own docs: >100 KB blobs belong in files. `SQLITE_MAX_MMAP_SIZE` is ~2 GB on a stock build. Scans 370–900 MB/s single-threaded. |
| DuckDB | stores `cell_id`, ~27 GB/material | ~8× current | "DuckDB is just not optimized for point queries… the smallest unit of work is not 1 row but 2,048." C++ API is documented as internal and unstable. |
| Parquet/Arrow | no 1-byte int type | 31 GB → 124 GB pre-compression | Page index spec: does "not support the equivalent of secondary indices over non-sorted data". |
| RocksDB | ~16 B/entry | ~124 GB + 9.7 GB of Bloom filters | Bloom filters carry zero information when every key exists. |
| LMDB | ~19 B/entry | ~148 GB, uncompressed | Its read path *is* mmap. You would add a B+tree on top of the mmap you already have. |
| ClickHouse/chDB | — | — | Own FAQ: "Can I use ClickHouse as a key-value storage? The short answer is **no**." 509 MB binary. Already slower per core than our scan. |

**And every one of their index tricks is dead on this data.** Zone maps,
row-group pruning and skip indexes all require matching cells to be
*clustered*. Measured on `KRvkbn` and `KQvkbn`, fraction of 65,536-cell blocks
that must still be read:

| predicate size | median block hit rate |
|---|---|
| <100 matches | 0.1–1.4% |
| 100–10k | 2–13% |
| 10k–1M | **31–41%** |
| `count == 1` alone | **95–97%** |

Coarsening the block size makes it worse. Spread is proportional to volume, not
concentrated. DuckDB's own guidance confirms the consequence: on randomly
ordered data "DuckDB will likely be unable to skip any row groups", and its
remedy — sorting by the filter column — would destroy the arithmetic
addressing that is the basis of O(1) probing.

**Syzygy corroborates the architecture.** Its entire public API is six
functions, all single-position point probes; there is no scan, no predicate, no
enumeration. Nalimov, Gaviota and Lomonosov are the same. The aggregate results
that field publishes (longest mates, DTM records) are one-off full scans done
at generation time and shipped as static lists — structurally identical to our
`.stats.json` sidecar. `mine` is novel territory: no prior art to copy a query
engine from, and none claiming a database is required. Syzygy's storage is
purpose-built files with fixed blocks, an offset index, mmap and an LRU cache —
the same shape as `table_file.cpp`, arrived at independently.

## What is worth building instead

Selectivity is extreme and that is the opportunity. Across the corpus's 180,864
`(dtm, count)` buckets, **97.1% match under 0.1% of a plane and 69.5% match
under 0.01%**. We read 100% of a plane to find 0.01% of it.

### Layer 0 — no index at all (approved)

Two changes, no new artifacts, no format change, no dependency. They speed up
**every** query, including the ones no index can ever help.

**Defer the count plane.** `Tablebase::mine` calls `read_values` with both
buffers, then rejects on `v.dtm != f.dtm` before ever consulting the count.
Roughly 80% of cells die on DTM alone. `read_values` already accepts a null
count buffer — `cmd_compact` uses exactly that. Scanning DTM first and
fetching counts only for survivors saves about half the decompression on a
compressed table, and nearly all of it for a rare `dtm`.

**Vectorise the predicate.** The scan is a scalar byte-at-a-time loop
(`tablebase.cpp`), measured at 757 M cells/s ≈ 1.5 GB/s single-threaded.
Published AVX2 byte-column scan rates are 3–5 G values/s. A `memchr`-shaped
compare plus parallelism across cores is plausibly 10–40×.

This layer ships first precisely so that Layers 1 and 2 are sized against an
*optimised* scan rather than against today's.

### Layer 1 — SQLite as catalogue and query planner (conditional)

The generator already writes `uniqueness[stm][dtm][count] = n` into every
sidecar (`generator.cpp`). **That is an exact 2-D histogram over both scan
predicates, sitting unread on disk.** Loading all 98 sidecars yields 180,864
rows — a few megabytes.

What that alone buys:

- **Exact hit counts with no scan.** The query-surface concept named live
  result counts as the TUI's real value *and* its hard part, listing streaming,
  sampling and caching as three options with three different failure modes. For
  the `dtm` and `count` dimensions there is a fourth with no failure mode: read
  the histogram. For theme filters, which do need enumeration, the same number
  is a correct upper bound to display while the scan runs.
- **Cross-material queries** without opening a plane — "which materials have
  h#4 positions with a unique solution, and how many".
- **A planner.** Knowing the candidate count *before* querying is what lets
  `mine` choose index-vs-scan, and order staged predicates cheapest-first,
  instead of guessing.
- **Catalogue and provenance** — materials, versions, encodings, block sizes,
  checksums, generation runs. The `helpmate list <dir>` backlog item falls out.

SQLite is the right container for this and the wrong one for cells; storing an
application's structured metadata is its documented purpose.

### Layer 2 — a tiered per-material index (conditional)

One uniform structure is wrong, because pruning power depends on cardinality.
A bucket with 12 matches touches at most 12 blocks — so block-granularity
pruning is 65,536× cheaper than cell-granularity and gets 99.4% of the win. At
224,677 matches the same block index prunes only 49%, because matches spread.

| bucket size | share of buckets | structure | corpus cost |
|---|---|---|---|
| <10k matches | 74.4% | exact cell ids, delta-packed | ~0.4 GB |
| 10k–1M | ~25% | block-existence bitmap | ~15 KB per predicate at 6 pieces |
| >1M | 0.4% | none — scan | 0 |

About 1.5% of corpus size for ~95% of possible queries. The block-existence
tier matters more than raw arithmetic suggests: on a compressed table **a
skipped block is a skipped decompression**, which is the dominant cost.

A *complete* per-value index is not an option and the arithmetic says so:
indexing all 20.5e9 solvable cells costs ~31 GB delta-packed — the size of the
corpus. Roaring bitmaps degrade to one bit per universe cell above 6.25%
density, and this data is scattered, so a full bitmap index measures larger
than the plane it indexes. The tiering is what makes an index affordable.

## Surface

The user's sketch was `helpmate gen --todb` then `helpmate mine --config`.
Adapted to a design where no cells are ingested:

- `helpmate index <material>` / `gen --index` — build the Layer 2 sidecar.
- `helpmate catalog <dir>` — build or refresh the Layer 1 SQLite catalogue
  from the sidecars already on disk. Cheap and repeatable; no table is read.
- `mine` gains no required flags. It consults the catalogue and index when
  present and scans when not, and says which it did.

`--config` is deferred deliberately. A config file is a good answer to *flag
overload*, which is the query-surface concept's subject, not this one; deciding
its format here would prejudge that design.

## Layering

- **Core** owns the scan, the index reader and the planner, as pure functions
  over a material and a filter.
- **The catalogue is derived, never authoritative.** It is rebuildable from
  the sidecars at any time, so it can never disagree with the tables for long,
  and losing it costs a rebuild rather than data.
- **The index is optional.** Every query must produce identical results with
  it absent — that is the central correctness claim and the thing the tests
  pin.
- **API/CLI/TUI/dashboard** consume the planner, never the index format.

## Verification

- **Index-vs-scan equivalence.** For every indexed bucket on a small material,
  `mine` with the index and `mine` with `--no-index` must return byte-identical
  output. Exhaustive at 3–4 pieces.
- **Catalogue-vs-truth.** Every count in the catalogue must equal the count a
  full scan produces. Checkable exhaustively on small materials and by
  sampling on large ones.
- **Layer 0 equivalence.** Deferring the count plane and vectorising must not
  change a single result; the existing raw-vs-compressed byte-identity checks
  extend to cover it.
- **Stale-artifact behaviour.** An index or catalogue older than its `.hm`
  must be detected and ignored with a diagnostic, never silently trusted.

## Out of scope

Ingesting cells into any database. Precomputing theme flags (rejected in the
session: astronomically expensive at 6 pieces and permanently blank for the
~65% of cells whose count saturates, which would make the index silently
under-report). Storing full solution sets. Changing the `.hm` format — the
index is a sidecar precisely so index design can evolve faster than the format
should. Remote/multi-user serving, which the user ranked below the search core
and which Layer 1 makes easier without being designed for here.

## Open questions

- **How much of the win is Layer 0?** This is the reason for the sequencing
  and cannot be answered before it is built.
- **Index granularity thresholds.** 10k and 1M are derived from corpus
  statistics, not from timing against an optimised scan. They should be set by
  measurement once Layer 0 exists.
- **Where the index lives** — one sidecar per material, or one file per
  `(material, side)`. Depends on whether partial indexes are useful.
- Two transferable Syzygy ideas, unmeasured and unrelated to querying:
  don't-care filling *inside* the compressor's dictionary phase (distinct from
  the pre-fill measured and rejected in the v4 doc), and a per-table
  permutation search over index orderings.
