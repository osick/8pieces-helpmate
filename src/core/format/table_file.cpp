#include "format/table_file.h"

#include <fcntl.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>

#include <algorithm>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <stdexcept>
#include <system_error>
#include <vector>

#include "format/block_codec.h"

namespace hm {

constexpr uint8_t kFlagAllUnsolvable = 0x01;

void TableWriter::write(const std::string& path, const Material& mat, uint64_t plane_size, uint8_t max_dtm,
                        const std::string& meta_json, const uint8_t* dtm_w, const uint8_t* dtm_b,
                        const uint8_t* cnt_w, const uint8_t* cnt_b) {
    TableHeader hdr{};
    std::memcpy(hdr.magic, "HM8P", 4);
    hdr.version = 1;
    hdr.encoding = 1;
    hdr.symmetry = mat.has_pawns() ? 0 : 1;
    std::memset(hdr.material, 0, sizeof(hdr.material));
    std::string name = mat.name();
    std::memcpy(hdr.material, name.data(), std::min(name.size(), sizeof(hdr.material)));
    hdr.plane_size = plane_size;
    hdr.max_dtm = max_dtm;
    std::memset(hdr.reserved, 0, sizeof(hdr.reserved));
    hdr.json_len = static_cast<uint32_t>(meta_json.size());

    std::string tmp_path = path + ".tmp";
    try {
        std::ofstream out(tmp_path, std::ios::binary | std::ios::trunc);
        if (!out) throw std::runtime_error("TableWriter::write: cannot open " + tmp_path);
        out.write(reinterpret_cast<const char*>(&hdr), sizeof(hdr));
        out.write(meta_json.data(), static_cast<std::streamsize>(meta_json.size()));
        out.write(reinterpret_cast<const char*>(dtm_w), static_cast<std::streamsize>(plane_size));
        out.write(reinterpret_cast<const char*>(dtm_b), static_cast<std::streamsize>(plane_size));
        out.write(reinterpret_cast<const char*>(cnt_w), static_cast<std::streamsize>(plane_size));
        out.write(reinterpret_cast<const char*>(cnt_b), static_cast<std::streamsize>(plane_size));
        if (!out) throw std::runtime_error("TableWriter::write: write failed for " + tmp_path);
    } catch (...) {
        std::error_code ec;
        std::filesystem::remove(tmp_path, ec);  // best-effort cleanup; ignore removal errors
        throw;
    }
    std::filesystem::rename(tmp_path, path);
}

void TableWriter::write_unsolvable(const std::string& path, const Material& mat, uint64_t plane_size,
                                   const std::string& meta_json) {
    TableHeader hdr{};
    std::memcpy(hdr.magic, "HM8P", 4);
    hdr.version = 2;  // marker tables only
    hdr.encoding = 1;
    hdr.symmetry = mat.has_pawns() ? 0 : 1;
    std::memset(hdr.material, 0, sizeof(hdr.material));
    std::string name = mat.name();
    std::memcpy(hdr.material, name.data(), std::min(name.size(), sizeof(hdr.material)));
    hdr.plane_size = plane_size;
    hdr.max_dtm = DTM_UNSOLVABLE;
    hdr.flags = kFlagAllUnsolvable;
    std::memset(hdr.reserved, 0, sizeof(hdr.reserved));
    hdr.json_len = static_cast<uint32_t>(meta_json.size());

    std::string tmp_path = path + ".tmp";
    try {
        std::ofstream out(tmp_path, std::ios::binary | std::ios::trunc);
        if (!out) throw std::runtime_error("TableWriter::write_unsolvable: cannot open " + tmp_path);
        out.write(reinterpret_cast<const char*>(&hdr), sizeof(hdr));
        out.write(meta_json.data(), static_cast<std::streamsize>(meta_json.size()));
        if (!out) throw std::runtime_error("TableWriter::write_unsolvable: write failed for " + tmp_path);
    } catch (...) {
        std::error_code ec;
        std::filesystem::remove(tmp_path, ec);  // best-effort cleanup; ignore removal errors
        throw;
    }
    std::filesystem::rename(tmp_path, path);
}

void TableWriter::write_compressed(const std::string& path, const Material& mat, uint64_t plane_size,
                                   uint8_t max_dtm, const std::string& meta_json, const uint8_t* dtm_w,
                                   const uint8_t* dtm_b, const uint8_t* cnt_w, const uint8_t* cnt_b,
                                   uint32_t block_size, int level) {
    if (block_size == 0) throw std::runtime_error("write_compressed: block_size is zero");
    TableHeader hdr{};
    std::memcpy(hdr.magic, "HM8P", 4);
    // Version 3 as well as encoding 2: the reader validates `encoding`, but only
    // `version` drives the "written by a newer helpmate" diagnostic, so a binary
    // released before this format says the useful thing instead of "unreadable".
    hdr.version = 3;
    hdr.encoding = kEncodingBlocks;
    hdr.symmetry = mat.has_pawns() ? 0 : 1;
    std::memset(hdr.material, 0, sizeof(hdr.material));
    std::string name = mat.name();
    std::memcpy(hdr.material, name.data(), std::min(name.size(), sizeof(hdr.material)));
    hdr.plane_size = plane_size;
    hdr.max_dtm = max_dtm;
    hdr.block_size = block_size;
    hdr.codec = kCodecZstd;
    std::memset(hdr.reserved, 0, sizeof(hdr.reserved));
    hdr.json_len = static_cast<uint32_t>(meta_json.size());

    // The four planes are one logical byte range, in the same order the raw
    // layout uses: dtm_w, dtm_b, cnt_w, cnt_b.
    const uint8_t* planes[4] = {dtm_w, dtm_b, cnt_w, cnt_b};
    const uint64_t logical = 4 * plane_size;
    const uint64_t nblocks = block_count(logical, block_size);

    std::string tmp_path = path + ".tmp";
    try {
        std::ofstream out(tmp_path, std::ios::binary | std::ios::trunc);
        if (!out) throw std::runtime_error("write_compressed: cannot open " + tmp_path);
        out.write(reinterpret_cast<const char*>(&hdr), sizeof(hdr));
        out.write(meta_json.data(), static_cast<std::streamsize>(meta_json.size()));

        // Reserve the index, then rewrite it once the offsets are known: a
        // one-pass writer would have to buffer the whole compressed payload.
        const std::streampos index_pos = out.tellp();
        std::vector<uint64_t> offsets(nblocks + 1, 0);
        out.write(reinterpret_cast<const char*>(&nblocks), sizeof(nblocks));
        out.write(reinterpret_cast<const char*>(offsets.data()),
                  static_cast<std::streamsize>(offsets.size() * sizeof(uint64_t)));

        std::vector<uint8_t> scratch(block_size);
        uint64_t written = 0;
        for (uint64_t b = 0; b < nblocks; ++b) {
            const uint64_t begin = b * block_size;
            const size_t len = static_cast<size_t>(std::min<uint64_t>(block_size, logical - begin));
            // Gather the block, which may straddle a plane boundary.
            for (size_t i = 0; i < len; ++i) {
                const uint64_t o = begin + i;
                scratch[i] = planes[o / plane_size][o % plane_size];
            }
            auto packed = compress_block(scratch.data(), len, level);
            offsets[b] = written;
            out.write(reinterpret_cast<const char*>(packed.data()),
                      static_cast<std::streamsize>(packed.size()));
            written += packed.size();
        }
        offsets[nblocks] = written;

        out.seekp(index_pos + static_cast<std::streamoff>(sizeof(uint64_t)));
        out.write(reinterpret_cast<const char*>(offsets.data()),
                  static_cast<std::streamsize>(offsets.size() * sizeof(uint64_t)));
        if (!out) throw std::runtime_error("write_compressed: write failed for " + tmp_path);
    } catch (...) {
        std::error_code ec;
        std::filesystem::remove(tmp_path, ec);
        throw;
    }
    std::filesystem::rename(tmp_path, path);
}

TableReader::TableReader(TableReader&& other) noexcept
    : base_(other.base_),
      map_size_(other.map_size_),
      ps_(other.ps_),
      json_len_(other.json_len_),
      block_size_(other.block_size_),
      nblocks_(other.nblocks_),
      offsets_(other.offsets_),
      blocks_(other.blocks_),
      cache_(std::move(other.cache_)) {
    other.reset();
}

TableReader& TableReader::operator=(TableReader&& other) noexcept {
    if (this != &other) {
        if (base_) munmap(const_cast<uint8_t*>(base_), map_size_);
        base_ = other.base_;
        map_size_ = other.map_size_;
        ps_ = other.ps_;
        json_len_ = other.json_len_;
        block_size_ = other.block_size_;
        nblocks_ = other.nblocks_;
        offsets_ = other.offsets_;
        blocks_ = other.blocks_;
        cache_ = std::move(other.cache_);
        other.reset();
    }
    return *this;
}

TableReader::~TableReader() {
    if (base_) munmap(const_cast<uint8_t*>(base_), map_size_);
}

void TableReader::reset() {
    base_ = nullptr;
    map_size_ = 0;
    ps_ = 0;
    json_len_ = 0;
    block_size_ = 0;
    nblocks_ = 0;
    offsets_ = nullptr;
    blocks_ = nullptr;
    cache_.reset();
}

std::optional<TableReader> TableReader::open(const std::string& path) {
    OpenError ignored = OpenError::None;
    return open(path, &ignored);
}

std::optional<TableReader> TableReader::open(const std::string& path, OpenError* err) {
    if (err) *err = OpenError::None;
    int fd = ::open(path.c_str(), O_RDONLY);
    if (fd < 0) {
        if (err) *err = OpenError::NotFound;
        return std::nullopt;
    }

    struct stat st{};
    if (fstat(fd, &st) != 0) {
        ::close(fd);
        if (err) *err = OpenError::NotFound;
        return std::nullopt;
    }
    size_t filesize = static_cast<size_t>(st.st_size);
    if (filesize < sizeof(TableHeader)) {
        ::close(fd);
        if (err) *err = OpenError::Unreadable;
        return std::nullopt;
    }

    void* mapped = mmap(nullptr, filesize, PROT_READ, MAP_SHARED, fd, 0);
    ::close(fd);  // fd not needed after mmap
    // Unreadable, not NotFound: open() and fstat() already succeeded, so the file
    // demonstrably exists. Reporting a mapping failure (ENOMEM, map-count limits,
    // an odd filesystem) as "missing" is the very confusion this overload exists
    // to prevent -- the caller would advise regenerating a table that is right there.
    if (mapped == MAP_FAILED) {
        if (err) *err = OpenError::Unreadable;
        return std::nullopt;
    }

    const uint8_t* base = static_cast<const uint8_t*>(mapped);
    const TableHeader* hdr = reinterpret_cast<const TableHeader*>(base);

    if (std::memcmp(hdr->magic, "HM8P", 4) != 0) {
        munmap(mapped, filesize);
        if (err) *err = OpenError::Unreadable;
        return std::nullopt;
    }

    // The magic is ours: the file IS a helpmate table. A version this build has never
    // heard of means it was written by a newer helpmate -- distinct from a malformed one.
    if (hdr->version > 3) {
        munmap(mapped, filesize);
        if (err) *err = OpenError::UnsupportedVersion;
        return std::nullopt;
    }

    // Validate without overflowable arithmetic: json_len and plane_size come from an
    // untrusted mmap'd header, and `4 * plane_size` can wrap mod 2^64 for crafted files.
    bool marker = (hdr->flags & kFlagAllUnsolvable) != 0;
    bool compressed = (hdr->version == 3);
    bool ok;
    if (compressed) {
        ok = !marker && hdr->encoding == kEncodingBlocks && hdr->codec == kCodecZstd && hdr->block_size > 0;
    } else {
        ok = (hdr->version == 1 || (hdr->version == 2 && marker)) && hdr->encoding == kEncodingRaw;
    }
    if (ok) {
        uint64_t after_header =
            filesize - sizeof(TableHeader);  // filesize >= sizeof(TableHeader) already checked
        if (hdr->json_len > after_header) {
            ok = false;
        } else {
            uint64_t remaining = after_header - hdr->json_len;
            if (compressed) {
                // `4 * plane_size` can wrap mod 2^64 for a crafted header -- guard
                // before the multiply, same discipline as the raw path above.
                if (hdr->plane_size > (UINT64_MAX / 4)) {
                    ok = false;
                } else {
                    uint64_t logical = 4 * hdr->plane_size;
                    uint64_t nb = block_count(logical, hdr->block_size);
                    // Enough room for the count and its offsets, and the offsets
                    // must describe a payload that fits in what is left.
                    if (nb > (UINT64_MAX - 2) / sizeof(uint64_t)) {
                        ok = false;
                    } else {
                        uint64_t index_bytes = sizeof(uint64_t) * (nb + 2);
                        ok = remaining >= index_bytes;
                        if (ok) {
                            const uint8_t* idx = base + sizeof(TableHeader) + hdr->json_len;
                            uint64_t stated;
                            std::memcpy(&stated, idx, sizeof(stated));
                            ok = (stated == nb);
                            if (ok) {
                                const uint64_t* offs =
                                    reinterpret_cast<const uint64_t*>(idx + sizeof(uint64_t));
                                const uint64_t payload_bytes = remaining - index_bytes;
                                ok = offs[nb] <= payload_bytes;
                                // Interior offsets are untrusted too: get()/byte_at() index
                                // blocks_ + offs[b] .. blocks_ + offs[b+1] without further
                                // checking, so a single out-of-bounds or decreasing entry
                                // reads (or feeds zstd) arbitrary memory. This is an O(n_blocks)
                                // scan at open time -- one sequential pass over the whole index,
                                // once per open, against a file that can be tens of GB; do not
                                // "optimise" it away by trusting the final offset alone.
                                if (ok && offs[0] != 0) ok = false;
                                if (ok) {
                                    for (uint64_t i = 0; ok && i < nb; ++i) { ok = offs[i] <= offs[i + 1]; }
                                }
                            }
                        }
                    }
                }
            } else {
                ok = marker ? (remaining == 0) : ((remaining % 4 == 0) && (hdr->plane_size == remaining / 4));
            }
        }
    }
    if (!ok) {
        munmap(mapped, filesize);
        if (err) *err = OpenError::Unreadable;
        return std::nullopt;
    }

    TableReader r;
    r.base_ = base;
    r.map_size_ = filesize;
    r.ps_ = hdr->plane_size;
    r.json_len_ = hdr->json_len;
    if (compressed) {
        const uint8_t* idx = base + sizeof(TableHeader) + hdr->json_len;
        std::memcpy(&r.nblocks_, idx, sizeof(r.nblocks_));
        r.offsets_ = reinterpret_cast<const uint64_t*>(idx + sizeof(uint64_t));
        r.blocks_ = idx + sizeof(uint64_t) * (r.nblocks_ + 2);
        r.block_size_ = hdr->block_size;
        r.cache_ = std::make_unique<BlockCache>(64, hdr->block_size);  // 64 blocks = 4 MB
    }
    return r;
}

ValuePair TableReader::get(Color stm, uint64_t cell) const {
    // Last line of defence: `cell` reaches here from a caller's index computation, and an
    // out-of-range value would otherwise read at base_ + <arbitrary offset> -- straight off
    // the end of the mapping, or (since the arithmetic wraps) anywhere at all.
    if (cell >= ps_)
        throw std::out_of_range("TableReader::get: cell " + std::to_string(cell) +
                                " out of range (plane size " + std::to_string(ps_) + ")");
    if (all_unsolvable()) return {DTM_UNSOLVABLE, 0};
    uint64_t o = (stm == Color::Black ? ps_ : 0) + cell;
    if (block_size_ == 0) {  // raw: unchanged
        const uint8_t* pay = base_ + sizeof(TableHeader) + json_len_;
        return {pay[o], pay[2 * ps_ + o]};
    }
    return {byte_at(o), byte_at(2 * ps_ + o)};
}

uint8_t TableReader::byte_at(uint64_t logical) const {
    const uint64_t b = logical / block_size_;
    const uint64_t begin = b * block_size_;
    const size_t len = static_cast<size_t>(std::min<uint64_t>(block_size_, 4 * ps_ - begin));
    const uint8_t* src = blocks_ + offsets_[b];
    const size_t clen = static_cast<size_t>(offsets_[b + 1] - offsets_[b]);
    return cache_->byte_at(b, static_cast<size_t>(logical - begin), len,
                           [&](uint8_t* dst, size_t n) { decompress_block(src, clen, dst, n); });
}

uint64_t TableReader::plane_size() const { return ps_; }

uint8_t TableReader::max_dtm() const { return reinterpret_cast<const TableHeader*>(base_)->max_dtm; }

std::string TableReader::material_name() const {
    const TableHeader* hdr = reinterpret_cast<const TableHeader*>(base_);
    return std::string(hdr->material, ::strnlen(hdr->material, sizeof(hdr->material)));
}

std::string TableReader::meta_json() const {
    return std::string(reinterpret_cast<const char*>(base_ + sizeof(TableHeader)), json_len_);
}

bool TableReader::all_unsolvable() const {
    return (reinterpret_cast<const TableHeader*>(base_)->flags & kFlagAllUnsolvable) != 0;
}

bool TableReader::is_compressed() const { return block_size_ != 0; }

}  // namespace hm
