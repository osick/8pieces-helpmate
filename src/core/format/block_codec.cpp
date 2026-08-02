#include "format/block_codec.h"

#include <zstd.h>

#include <memory>
#include <stdexcept>
#include <string>

namespace hm {

namespace {

struct ZstdCCtxDeleter {
    void operator()(ZSTD_CCtx* ctx) const noexcept { ZSTD_freeCCtx(ctx); }
};
using ZstdCCtxPtr = std::unique_ptr<ZSTD_CCtx, ZstdCCtxDeleter>;

}  // namespace

uint64_t block_count(uint64_t logical_size, uint32_t block_size) {
    if (block_size == 0) throw std::runtime_error("block_count: block_size is zero");
    return (logical_size + block_size - 1) / block_size;
}

size_t max_compressed_size(size_t n) { return ZSTD_compressBound(n); }

std::vector<uint8_t> compress_block(const uint8_t* src, size_t n, int level) {
    std::vector<uint8_t> out(ZSTD_compressBound(n));

    // A tablebase that silently returns a wrong DTM is worse than one that
    // fails loudly: without this flag zstd only catches structural damage, and
    // a measured majority of single-bit flips on a realistic block decoded to
    // wrong-but-valid data. Costs 4 bytes per block -- 0.006% at the 64 KB
    // default. ZSTD_compress() (the simple API) cannot set this, hence the
    // context API here.
    ZstdCCtxPtr ctx(ZSTD_createCCtx());
    if (!ctx) throw std::runtime_error("zstd: could not create compression context");

    size_t rc = ZSTD_CCtx_setParameter(ctx.get(), ZSTD_c_compressionLevel, level);
    if (ZSTD_isError(rc))
        throw std::runtime_error(std::string("zstd: could not set compression level: ") +
                                 ZSTD_getErrorName(rc));

    rc = ZSTD_CCtx_setParameter(ctx.get(), ZSTD_c_checksumFlag, 1);
    if (ZSTD_isError(rc))
        throw std::runtime_error(std::string("zstd: could not enable checksum: ") + ZSTD_getErrorName(rc));

    size_t written = ZSTD_compress2(ctx.get(), out.data(), out.size(), src, n);
    if (ZSTD_isError(written))
        throw std::runtime_error(std::string("zstd compress failed: ") + ZSTD_getErrorName(written));
    out.resize(written);
    return out;
}

void decompress_block(const uint8_t* src, size_t n, uint8_t* dst, size_t dst_capacity) {
    size_t got = ZSTD_decompress(dst, dst_capacity, src, n);
    if (ZSTD_isError(got))
        throw std::runtime_error(std::string("zstd decompress failed: ") + ZSTD_getErrorName(got));
    // A block that decompresses to a different length than the caller expects
    // means the index and the payload disagree -- a corrupt or truncated file,
    // not a recoverable condition.
    if (got != dst_capacity)
        throw std::runtime_error("zstd decompress: expected " + std::to_string(dst_capacity) +
                                 " bytes, got " + std::to_string(got));
}

}  // namespace hm
