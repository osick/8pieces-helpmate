#include "format/table_file.h"

#include <cstring>
#include <filesystem>
#include <fstream>
#include <stdexcept>
#include <system_error>

#include <fcntl.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>

namespace hm {

void TableWriter::write(const std::string& path, const Material& mat, uint64_t plane_size, uint8_t max_dtm,
                         const std::string& meta_json,
                         const uint8_t* dtm_w, const uint8_t* dtm_b,
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

TableReader::TableReader(TableReader&& other) noexcept
    : base_(other.base_), map_size_(other.map_size_), ps_(other.ps_), json_len_(other.json_len_) {
    other.reset();
}

TableReader& TableReader::operator=(TableReader&& other) noexcept {
    if (this != &other) {
        if (base_) munmap(const_cast<uint8_t*>(base_), map_size_);
        base_ = other.base_;
        map_size_ = other.map_size_;
        ps_ = other.ps_;
        json_len_ = other.json_len_;
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
}

std::optional<TableReader> TableReader::open(const std::string& path) {
    int fd = ::open(path.c_str(), O_RDONLY);
    if (fd < 0) return std::nullopt;

    struct stat st{};
    if (fstat(fd, &st) != 0) { ::close(fd); return std::nullopt; }
    size_t filesize = static_cast<size_t>(st.st_size);
    if (filesize < sizeof(TableHeader)) { ::close(fd); return std::nullopt; }

    void* mapped = mmap(nullptr, filesize, PROT_READ, MAP_SHARED, fd, 0);
    ::close(fd);  // fd not needed after mmap
    if (mapped == MAP_FAILED) return std::nullopt;

    const uint8_t* base = static_cast<const uint8_t*>(mapped);
    const TableHeader* hdr = reinterpret_cast<const TableHeader*>(base);

    // Validate without overflowable arithmetic: json_len and plane_size come from an
    // untrusted mmap'd header, and `4 * plane_size` can wrap mod 2^64 for crafted files.
    bool ok = std::memcmp(hdr->magic, "HM8P", 4) == 0 &&
              hdr->version == 1 &&
              hdr->encoding == 1;
    if (ok) {
        uint64_t after_header = filesize - sizeof(TableHeader);  // filesize >= sizeof(TableHeader) already checked
        if (hdr->json_len > after_header) {
            ok = false;
        } else {
            uint64_t remaining = after_header - hdr->json_len;
            ok = (remaining % 4 == 0) && (hdr->plane_size == remaining / 4);
        }
    }
    if (!ok) {
        munmap(mapped, filesize);
        return std::nullopt;
    }

    TableReader r;
    r.base_ = base;
    r.map_size_ = filesize;
    r.ps_ = hdr->plane_size;
    r.json_len_ = hdr->json_len;
    return r;
}

ValuePair TableReader::get(Color stm, uint64_t cell) const {
    // Last line of defence: `cell` reaches here from a caller's index computation, and an
    // out-of-range value would otherwise read at base_ + <arbitrary offset> -- straight off
    // the end of the mapping, or (since the arithmetic wraps) anywhere at all.
    if (cell >= ps_)
        throw std::out_of_range("TableReader::get: cell " + std::to_string(cell) +
                                " out of range (plane size " + std::to_string(ps_) + ")");
    const uint8_t* pay = base_ + sizeof(TableHeader) + json_len_;
    uint64_t o = (stm == Color::Black ? ps_ : 0) + cell;
    return { pay[o], pay[2 * ps_ + o] };
}

uint64_t TableReader::plane_size() const {
    return ps_;
}

uint8_t TableReader::max_dtm() const {
    return reinterpret_cast<const TableHeader*>(base_)->max_dtm;
}

std::string TableReader::material_name() const {
    const TableHeader* hdr = reinterpret_cast<const TableHeader*>(base_);
    return std::string(hdr->material, ::strnlen(hdr->material, sizeof(hdr->material)));
}

std::string TableReader::meta_json() const {
    return std::string(reinterpret_cast<const char*>(base_ + sizeof(TableHeader)), json_len_);
}

}  // namespace hm
