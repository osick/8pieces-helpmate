#pragma once
#include <cstdint>
#include <memory>
#include <optional>
#include <string>

#include "chess/types.h"
#include "format/block_cache.h"
#include "indexing/material.h"

namespace hm {

constexpr uint8_t kEncodingRaw = 1;     // 4 contiguous byte planes
constexpr uint8_t kEncodingBlocks = 2;  // block index + compressed blocks
constexpr uint8_t kCodecNone = 0;
constexpr uint8_t kCodecZstd = 1;
// 64 KiB/level 3. `helpmate mine`'s --count/--starts path probes child
// positions effectively at random, so on a real table nearly every probe
// misses the reader's decompressed-block cache and pays a full block
// decompress for one byte -- measured ~6.5x slower end to end than raw on
// a 462 MiB table. A plain sequential scan or a single probe barely notices
// block size (measured 9-14% either way).
//
// A 16 KiB default was tried on the theory that smaller blocks would cut
// the mining regression (less to decompress per miss). Measured on the same
// 462 MiB table it did NOT: 16 KiB and 64 KiB both ran ~6.5x slower than raw
// on `mine --count`, while 16 KiB compressed worse (5.94x ratio, 77.8 MiB)
// than 64 KiB (6.53x ratio, 70.8 MiB). Decompression is evidently not the
// bottleneck -- the per-miss overhead in BlockCache is the suspect, but that
// is unconfirmed and needs profiling, not another guessed block size. See
// docs/USAGE.md's Table format section for the full numbers and
// tools/bench_compression.py to reproduce them. Retune only with a
// measurement.
constexpr uint32_t kDefaultBlockSize = 65536;
// Ceiling enforced at open(): block_size is retunable per file with no
// version bump, so a crafted header can otherwise claim an arbitrary value.
// The reader sizes its decompressed-block cache from block_size (see
// kBlockCacheBytes in table_file.cpp), so an unbounded value is a memory
// exhaustion vector on the very first get() -- reject it before that point
// instead.
constexpr uint32_t kMaxBlockSize = 16 * 1024 * 1024;
constexpr int kDefaultZstdLevel = 3;

#pragma pack(push, 1)
struct TableHeader {
    char magic[4];      // "HM8P"
    uint32_t version;   // 1 = ordinary table, 2 = all-unsolvable marker (see flags)
    uint8_t encoding;   // 1 = raw byte planes
    uint8_t symmetry;   // 0 = with pawns (2 transforms), 1 = pawnless (8)
    char material[26];  // canonical name, NUL padded
    uint64_t plane_size;
    uint8_t max_dtm;      // DTM_UNSOLVABLE if no cell solvable
    uint8_t flags;        // bit 0: all-unsolvable marker (no payload follows)
    uint32_t block_size;  // encoding 2: UNCOMPRESSED bytes per block; 0 when raw
    uint8_t codec;        // encoding 2: kCodecZstd; kCodecNone when raw
    uint8_t reserved[9];
    uint32_t json_len;  // metadata JSON directly after header
};
#pragma pack(pop)
static_assert(sizeof(TableHeader) == 64);
// payload after JSON: 4 planes of plane_size bytes each: dtm_wtm, dtm_btm, cnt_wtm, cnt_btm

class TableReader;  // defined below; TableWriter::compress_existing takes one by reference

struct TableWriter {  // writes "<path>.tmp" then atomic-renames to path
    static void write(const std::string& path, const Material&, uint64_t plane_size, uint8_t max_dtm,
                      const std::string& meta_json, const uint8_t* dtm_w, const uint8_t* dtm_b,
                      const uint8_t* cnt_w, const uint8_t* cnt_b);

    // Marker table: header + JSON, no planes. Every cell reads as
    // DTM_UNSOLVABLE. Written with version 2; ordinary tables stay version 1.
    static void write_unsolvable(const std::string& path, const Material&, uint64_t plane_size,
                                 const std::string& meta_json);

    // Block-compressed variant: version 3, encoding 2. Compresses at finalize,
    // never inside the generator's hot loop.
    static void write_compressed(const std::string& path, const Material&, uint64_t plane_size,
                                 uint8_t max_dtm, const std::string& meta_json, const uint8_t* dtm_w,
                                 const uint8_t* dtm_b, const uint8_t* cnt_w, const uint8_t* cnt_b,
                                 uint32_t block_size = kDefaultBlockSize, int level = kDefaultZstdLevel);

    // Rewrites a table (raw OR already block-compressed) as block-compressed
    // at `block_size`, streaming rather than buffering the four planes --
    // buffering would need 4 * plane_size bytes, which is 31 GB for a
    // six-piece table. A raw source streams straight off its mmap at
    // constant memory (SequentialPageReleaser drops consumed pages as it
    // goes). A compressed source (re-blocking, e.g. moving a table from 64
    // KiB to 16 KiB blocks without regenerating it) streams through
    // TableReader::read_range instead, bounded by that reader's own
    // decompressed-block cache (a few MB), never the whole table. Throws
    // only for a marker table (no payload to stream at all).
    static void compress_existing(const std::string& path, const TableReader& src,
                                  uint32_t block_size = kDefaultBlockSize, int level = kDefaultZstdLevel);
};

class TableReader {  // mmap; movable, not copyable
public:
    TableReader(const TableReader&) = delete;
    TableReader& operator=(const TableReader&) = delete;
    TableReader(TableReader&&) noexcept;
    TableReader& operator=(TableReader&&) noexcept;
    ~TableReader();

    static std::optional<TableReader> open(const std::string& path);

    // Why open() returned nullopt. UnsupportedVersion means the file IS a helpmate
    // table, but was written by a newer build than this one.
    enum class OpenError { None, NotFound, Unreadable, UnsupportedVersion };
    static std::optional<TableReader> open(const std::string& path, OpenError* err);
    ValuePair get(Color stm, uint64_t cell) const;
    uint64_t plane_size() const;
    uint8_t max_dtm() const;
    std::string material_name() const;
    std::string meta_json() const;
    bool all_unsolvable() const;
    bool is_compressed() const;
    // UNCOMPRESSED bytes per block for a compressed table; 0 for raw (there
    // are no blocks) or a marker.
    uint32_t block_size() const;

    // Pointer to the first of the 4 contiguous plane_size-byte planes (dtm_w,
    // dtm_b, cnt_w, cnt_b), for streaming a raw table's payload without
    // copying it. nullptr for a compressed table (its payload isn't a flat
    // byte range) and for a marker (it has no payload at all).
    const uint8_t* raw_payload() const;

    // Copies `len` logical bytes starting at `logical_offset` into `dst`.
    // Works for raw and block-compressed tables alike, so a converter can
    // re-block a compressed table without a decompress-to-disk round trip.
    // For a raw table this is a memcpy straight off the mapping; for a
    // compressed one it decompresses each block the range overlaps -- once
    // per block per call, through this reader's own bounded block cache, not
    // once per byte -- and copies out the overlapping span. Sequential
    // callers (e.g. compress_existing re-blocking) therefore decompress each
    // source block exactly once as they stream forward, as long as the
    // cache's capacity keeps up with how far ahead a caller reads.
    void read_range(uint64_t logical_offset, size_t len, uint8_t* dst) const;

private:
    TableReader() = default;
    void reset();
    uint8_t byte_at(uint64_t logical) const;

    const uint8_t* base_ = nullptr;
    size_t map_size_ = 0;
    uint64_t ps_ = 0;
    uint32_t json_len_ = 0;

    uint32_t block_size_ = 0;  // 0 => raw
    uint64_t nblocks_ = 0;
    // nblocks_+1 raw uint64 entries, into the mapping. `const uint8_t*`, not
    // `const uint64_t*`: the offset from the start of the mapping depends on
    // json_len, an arbitrary value from the file, so this is not generally
    // 8-byte aligned. Read entries with load_u64() in table_file.cpp, never
    // by dereferencing a uint64_t* cast of this pointer.
    const uint8_t* offsets_ = nullptr;
    const uint8_t* blocks_ = nullptr;  // first compressed byte
    mutable std::unique_ptr<BlockCache> cache_;
};

}  // namespace hm
