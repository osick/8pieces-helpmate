#pragma once
#include "chess/types.h"
#include "indexing/material.h"
#include <cstdint>
#include <optional>
#include <string>

namespace hm {

#pragma pack(push, 1)
struct TableHeader {
    char magic[4];            // "HM8P"
    uint32_t version;         // 1 = ordinary table, 2 = all-unsolvable marker (see flags)
    uint8_t encoding;         // 1 = raw byte planes
    uint8_t symmetry;         // 0 = with pawns (2 transforms), 1 = pawnless (8)
    char material[26];        // canonical name, NUL padded
    uint64_t plane_size;
    uint8_t max_dtm;          // DTM_UNSOLVABLE if no cell solvable
    uint8_t flags;            // bit 0: all-unsolvable marker (no payload follows)
    uint8_t reserved[14];
    uint32_t json_len;        // metadata JSON directly after header
};
#pragma pack(pop)
static_assert(sizeof(TableHeader) == 64);
// payload after JSON: 4 planes of plane_size bytes each: dtm_wtm, dtm_btm, cnt_wtm, cnt_btm

struct TableWriter {          // writes "<path>.tmp" then atomic-renames to path
    static void write(const std::string& path, const Material&, uint64_t plane_size, uint8_t max_dtm,
                      const std::string& meta_json,
                      const uint8_t* dtm_w, const uint8_t* dtm_b,
                      const uint8_t* cnt_w, const uint8_t* cnt_b);

    // Marker table: header + JSON, no planes. Every cell reads as
    // DTM_UNSOLVABLE. Written with version 2; ordinary tables stay version 1.
    static void write_unsolvable(const std::string& path, const Material&,
                                 uint64_t plane_size, const std::string& meta_json);
};

class TableReader {           // mmap; movable, not copyable
public:
    TableReader(const TableReader&) = delete;
    TableReader& operator=(const TableReader&) = delete;
    TableReader(TableReader&&) noexcept;
    TableReader& operator=(TableReader&&) noexcept;
    ~TableReader();

    static std::optional<TableReader> open(const std::string& path);
    ValuePair get(Color stm, uint64_t cell) const;
    uint64_t plane_size() const;
    uint8_t max_dtm() const;
    std::string material_name() const;
    std::string meta_json() const;
    bool all_unsolvable() const;

private:
    TableReader() = default;
    void reset();

    const uint8_t* base_ = nullptr;
    size_t map_size_ = 0;
    uint64_t ps_ = 0;
    uint32_t json_len_ = 0;
};

}  // namespace hm
