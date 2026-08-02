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
constexpr uint32_t kDefaultBlockSize = 65536;  // 14.5x at zstd level 3; see the spec
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

    // Rewrites a RAW table as block-compressed, streaming off its mapping at
    // constant memory. Buffering the planes would need 4 * plane_size bytes,
    // which is 31 GB for a six-piece table.
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

    // Pointer to the first of the 4 contiguous plane_size-byte planes (dtm_w,
    // dtm_b, cnt_w, cnt_b), for streaming a raw table's payload without
    // copying it. nullptr for a compressed table (its payload isn't a flat
    // byte range) and for a marker (it has no payload at all).
    const uint8_t* raw_payload() const;

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
