# Block-Compressed Tables (v0.7.5) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Store table planes as independently-compressed fixed-size blocks so a 31 GB table becomes roughly 2 GB, without giving up the byte-addressable random access that probing depends on.

**Architecture:** A new on-disk encoding (`version = 3`, `encoding = 2`) appends a block-offset index after the JSON, then zstd-compressed blocks. The four planes are addressed as one logical byte range of `4 × plane_size` and cut into fixed 64 KB chunks. `TableReader` keeps `mmap` for the header and index and gains a bounded LRU of decompressed blocks; the raw path is untouched. Writing compresses at finalize, never inside the generator's hot loop.

**Tech Stack:** C++20, CMake, libzstd (system package), Catch2, ctest.

Spec: `docs/superpowers/specs/2026-08-02-block-compression-design.md`

**Prerequisite, once, on the development machine:**

```bash
sudo zypper install libzstd-devel     # openSUSE Leap 15.5; repo-oss has 1.5.0
```

CI installs `libzstd-dev` via apt. Nothing else is needed.

**Branch.** All tasks land on `v0.7.5-compression`, which already exists and holds the spec commit.

## Global Constraints

- **Max 4 cores.** Prefix every build/test command with `taskset -c 0-3`.
- **NEVER touch `~/tb`** except to read. A 6-piece generation run is writing there; the corpus is 89.7 GB and irreplaceable. Every scratch table goes in `$(mktemp -d)`.
- **Never run bare `./build/helpmate_tests`** — always `"~[slow]"`, or the 30–60 minute slow lane runs.
- **Do not delete `build/` or `build/_deps`.** A fresh FetchContent clone hangs forever on an invisible SSH passphrase dialog on this machine. Reconfigure in place with `taskset -c 0-3 cmake -S . -B build`.
- **Prefix any `pip install` with `GIT_CONFIG_GLOBAL=/dev/null`** and use `CC=gcc-13 CXX=g++-13`; the default compiler is GCC 7.5 and cannot compile C++20.
- **Never wait on a process with `until ! pgrep -f "<pattern>"`** — `pgrep -f` matches the waiting shell's own command line and the loop never exits.
- **ctest must total 117 plus whatever this plan adds**, and the count must be stated in each task that changes it. `./build/helpmate_tests "~[slow]"` must report 86 cases plus additions.
- **`make lint`, `make typecheck`, `make format-check` must all exit 0** before any commit — `main` is branch-protected and a PR cannot merge otherwise. `make format-check` enforces C++ formatting on changed lines only, so new code must be formatted even though the surrounding file is not.
- Commit trailer, exactly: `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`

## File Structure

| file | responsibility |
|---|---|
| `src/core/format/block_codec.h` / `.cpp` | **new.** Pure compression: block sizing, compress/decompress one block, the offset-index layout. No file I/O, no mmap, no zstd types in the header. |
| `src/core/format/block_cache.h` / `.cpp` | **new.** Bounded LRU of decompressed blocks, with the mutex. No knowledge of tables. |
| `src/core/format/table_file.h` / `.cpp` | header fields, the compressed write path, reader dispatch between raw and compressed `get()`. |
| `src/core/tests/test_block_codec.cpp` | **new.** Codec and cache unit tests. |
| `src/core/tests/test_table_file.cpp` | extended: round-trip equality, short final block, diagnostics. |
| `src/packages/cli/main.cpp` | `gen --compress`, `compact --compress`. |
| `src/core/CMakeLists.txt`, root `CMakeLists.txt` | `find_package` for zstd, source list. |

`block_codec` and `block_cache` are separate from `table_file` deliberately: both are pure and exhaustively testable without writing a file, and `table_file.cpp` is already 200+ lines of mmap and validation logic that should not also own a compression algorithm.

---

### Task 1: Build dependency and header fields

Adds libzstd to the build and claims the header bytes, with nothing yet reading or writing them. Separate from Task 2 so a `find_package` failure is diagnosed on its own.

**Files:**
- Modify: `CMakeLists.txt` (root — the `find_package` next to `find_package(Threads REQUIRED)`)
- Modify: `src/core/CMakeLists.txt` (link zstd into `helpmate_core`)
- Modify: `src/core/format/table_file.h` (header struct)
- Modify: `src/core/tests/test_table_file.cpp` (size and layout assertions)
- Modify: `docs/BUILD.md` (prerequisite)

**Interfaces:**
- Consumes: nothing.
- Produces: `TableHeader::block_size` (uint32), `TableHeader::codec` (uint8), still `sizeof(TableHeader) == 64`. The constants `kCodecNone = 0`, `kCodecZstd = 1`, `kDefaultBlockSize = 65536`, `kEncodingRaw = 1`, `kEncodingBlocks = 2`, all in `namespace hm` in `table_file.h`.

- [ ] **Step 1: Write the failing test**

Add to `src/core/tests/test_table_file.cpp`:

```cpp
TEST_CASE("header keeps its 64-byte layout after claiming reserved bytes") {
    static_assert(sizeof(hm::TableHeader) == 64);
    // The two new fields come out of `reserved`, which was 14 bytes.
    hm::TableHeader h{};
    h.block_size = 65536;
    h.codec = hm::kCodecZstd;
    CHECK(h.block_size == 65536u);
    CHECK(h.codec == 1);
    CHECK(sizeof(h.reserved) == 9);
    // A default-constructed header must still describe a raw table, so any
    // code path that forgets to set these does not silently claim compression.
    hm::TableHeader zero{};
    CHECK(zero.codec == hm::kCodecNone);
    CHECK(zero.block_size == 0u);
}
```

- [ ] **Step 2: Run it to verify it fails**

```bash
taskset -c 0-3 cmake --build build -j4 2>&1 | tail -5
```
Expected: compile error — `TableHeader` has no member `block_size`.

- [ ] **Step 3: Claim the header bytes**

In `src/core/format/table_file.h`, replace `uint8_t reserved[14];` with:

```cpp
    uint32_t block_size;      // encoding 2: UNCOMPRESSED bytes per block; 0 when raw
    uint8_t  codec;           // encoding 2: kCodecZstd; kCodecNone when raw
    uint8_t  reserved[9];
```

and add above the struct:

```cpp
constexpr uint8_t kEncodingRaw = 1;      // 4 contiguous byte planes
constexpr uint8_t kEncodingBlocks = 2;   // block index + compressed blocks
constexpr uint8_t kCodecNone = 0;
constexpr uint8_t kCodecZstd = 1;
constexpr uint32_t kDefaultBlockSize = 65536;   // 14.5x at zstd level 3; see the spec
constexpr int kDefaultZstdLevel = 3;
```

The existing `static_assert(sizeof(TableHeader) == 64)` stays and must still hold: 4 + 1 + 9 = 14, the same bytes `reserved` occupied.

- [ ] **Step 4: Add zstd to the build**

In the root `CMakeLists.txt`, immediately after `find_package(Threads REQUIRED)`:

```cmake
# zstd is a hard requirement, deliberately a system package rather than a
# fourth FetchContent clone: this machine's gitconfig rewrites GitHub HTTPS to
# SSH, and a clone that hangs on an invisible passphrase dialog is far worse
# than a configure-time error that names the package to install.
find_package(PkgConfig QUIET)
if(PkgConfig_FOUND)
  pkg_check_modules(ZSTD IMPORTED_TARGET libzstd)
endif()
if(NOT ZSTD_FOUND)
  find_path(ZSTD_INCLUDE_DIR zstd.h)
  find_library(ZSTD_LIBRARY NAMES zstd)
  if(NOT ZSTD_INCLUDE_DIR OR NOT ZSTD_LIBRARY)
    message(FATAL_ERROR
      "libzstd headers not found -- install libzstd-devel (openSUSE) "
      "or libzstd-dev (Debian/Ubuntu)")
  endif()
  add_library(PkgConfig::ZSTD UNKNOWN IMPORTED)
  set_target_properties(PkgConfig::ZSTD PROPERTIES
    IMPORTED_LOCATION "${ZSTD_LIBRARY}"
    INTERFACE_INCLUDE_DIRECTORIES "${ZSTD_INCLUDE_DIR}")
endif()
```

In `src/core/CMakeLists.txt`, add `PkgConfig::ZSTD` to the existing
`target_link_libraries(helpmate_core PUBLIC ...)` line.

**Note on this machine:** `pkg-config --modversion libzstd` currently returns nothing even with the library present, so the `find_path`/`find_library` fallback is the path that will actually be taken here. Both branches must work; do not delete the fallback because pkg-config happens to work on CI.

- [ ] **Step 5: Verify it builds and links**

```bash
taskset -c 0-3 cmake -S . -B build 2>&1 | tail -3
taskset -c 0-3 cmake --build build -j4 2>&1 | tail -3
taskset -c 0-3 ctest --test-dir build --output-on-failure | tail -3
```
Expected: configure succeeds naming zstd, build succeeds, **118/118** tests pass (117 plus the new Catch2 case).

Then prove the error path is real — a broken build message is the whole point of Step 4:

```bash
taskset -c 0-3 cmake -S . -B /tmp/zstd-probe -DCMAKE_DISABLE_FIND_PACKAGE_PkgConfig=ON \
  -DZSTD_INCLUDE_DIR=ZSTD_INCLUDE_DIR-NOTFOUND -DZSTD_LIBRARY=ZSTD_LIBRARY-NOTFOUND 2>&1 | tail -4
rm -rf /tmp/zstd-probe
```
Expected: `libzstd headers not found -- install libzstd-devel ...`. Report the actual message.

- [ ] **Step 6: Document the prerequisite and commit**

In `docs/BUILD.md`, next to the GCC-13 prerequisite, add libzstd with both package names and the one-line reason (block-compressed tables, v0.7.5+).

```bash
git add -A
git commit -m "build: require libzstd, claim header bytes for block encoding

block_size and codec come out of the header's reserved 14 bytes, so the
struct stays 64 bytes and existing files are unaffected. zstd is a system
package rather than a fourth FetchContent clone -- a configure-time error
naming the package beats a clone that hangs on an SSH passphrase dialog.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: The block codec

Pure compression, no file I/O. Everything here is exhaustively testable in memory, which is why it is its own file and its own task.

**Files:**
- Create: `src/core/format/block_codec.h`, `src/core/format/block_codec.cpp`
- Create: `src/core/tests/test_block_codec.cpp`
- Modify: `src/core/CMakeLists.txt` (both source lists)

**Interfaces:**
- Consumes: `kDefaultBlockSize`, `kDefaultZstdLevel` from Task 1.
- Produces:
  - `uint64_t block_count(uint64_t logical_size, uint32_t block_size)`
  - `std::vector<uint8_t> compress_block(const uint8_t* src, size_t n, int level)`
  - `void decompress_block(const uint8_t* src, size_t n, uint8_t* dst, size_t dst_capacity)` — throws `std::runtime_error` on a corrupt block or a size mismatch
  - `size_t max_compressed_size(size_t n)`

- [ ] **Step 1: Write the failing tests**

Create `src/core/tests/test_block_codec.cpp`:

```cpp
#include <catch2/catch_test_macros.hpp>
#include "format/block_codec.h"
#include "chess/types.h"
#include <numeric>
#include <random>
#include <stdexcept>
#include <vector>

using namespace hm;

TEST_CASE("block_count rounds up and handles an exact multiple") {
    CHECK(block_count(0, 1024) == 0);
    CHECK(block_count(1, 1024) == 1);
    CHECK(block_count(1024, 1024) == 1);
    CHECK(block_count(1025, 1024) == 2);
    CHECK(block_count(4ull * 7'751'073'792ull, 65536) == 473'115ull);
}

TEST_CASE("a block round-trips byte for byte") {
    std::vector<uint8_t> src(65536);
    std::mt19937 rng(12345);
    for (auto& b : src) b = static_cast<uint8_t>(rng() & 0xFF);
    auto packed = compress_block(src.data(), src.size(), kDefaultZstdLevel);
    std::vector<uint8_t> back(src.size());
    decompress_block(packed.data(), packed.size(), back.data(), back.size());
    CHECK(back == src);
}

TEST_CASE("a constant block compresses hard and still round-trips") {
    // Half of a real 6-piece plane is DTM_INVALID; this is the case the whole
    // format exists to exploit, so it is pinned rather than assumed.
    std::vector<uint8_t> src(65536, DTM_INVALID);
    auto packed = compress_block(src.data(), src.size(), kDefaultZstdLevel);
    CHECK(packed.size() < src.size() / 50);
    std::vector<uint8_t> back(src.size());
    decompress_block(packed.data(), packed.size(), back.data(), back.size());
    CHECK(back == src);
}

TEST_CASE("a short final block round-trips at its own length") {
    // 4 * plane_size is not a multiple of 65536 in general.
    std::vector<uint8_t> src(1237);
    std::iota(src.begin(), src.end(), 0);
    auto packed = compress_block(src.data(), src.size(), kDefaultZstdLevel);
    std::vector<uint8_t> back(src.size());
    decompress_block(packed.data(), packed.size(), back.data(), back.size());
    CHECK(back == src);
}

TEST_CASE("a corrupt block throws instead of returning garbage") {
    std::vector<uint8_t> src(4096, 7);
    auto packed = compress_block(src.data(), src.size(), kDefaultZstdLevel);
    REQUIRE(packed.size() > 8);
    packed[packed.size() / 2] ^= 0xFF;          // flip a bit in the middle
    std::vector<uint8_t> back(src.size());
    CHECK_THROWS_AS(decompress_block(packed.data(), packed.size(), back.data(), back.size()),
                    std::runtime_error);
}

TEST_CASE("a block that decompresses to the wrong size throws") {
    std::vector<uint8_t> src(4096, 7);
    auto packed = compress_block(src.data(), src.size(), kDefaultZstdLevel);
    std::vector<uint8_t> back(2048);            // caller expects half
    CHECK_THROWS_AS(decompress_block(packed.data(), packed.size(), back.data(), back.size()),
                    std::runtime_error);
}
```

- [ ] **Step 2: Run to verify it fails**

Add `format/block_codec.cpp` to `HELPMATE_SOURCES` and `tests/test_block_codec.cpp` to the `helpmate_tests` source list in `src/core/CMakeLists.txt`, then:

```bash
taskset -c 0-3 cmake -S . -B build && taskset -c 0-3 cmake --build build -j4 2>&1 | tail -5
```
Expected: `block_codec.h: No such file or directory`.

- [ ] **Step 3: Implement**

`src/core/format/block_codec.h`:

```cpp
#pragma once
#include <cstddef>
#include <cstdint>
#include <vector>

namespace hm {

// Blocks are compressed INDEPENDENTLY. A single stream would compress better
// but destroy random access, which is the whole point of the table format.
uint64_t block_count(uint64_t logical_size, uint32_t block_size);
size_t max_compressed_size(size_t n);
std::vector<uint8_t> compress_block(const uint8_t* src, size_t n, int level);
// Throws std::runtime_error if the block is corrupt or does not decompress to
// exactly dst_capacity bytes.
void decompress_block(const uint8_t* src, size_t n, uint8_t* dst, size_t dst_capacity);

}  // namespace hm
```

`src/core/format/block_codec.cpp`:

```cpp
#include "format/block_codec.h"

#include <stdexcept>
#include <string>

#include <zstd.h>

namespace hm {

uint64_t block_count(uint64_t logical_size, uint32_t block_size) {
    if (block_size == 0) throw std::runtime_error("block_count: block_size is zero");
    return (logical_size + block_size - 1) / block_size;
}

size_t max_compressed_size(size_t n) { return ZSTD_compressBound(n); }

std::vector<uint8_t> compress_block(const uint8_t* src, size_t n, int level) {
    std::vector<uint8_t> out(ZSTD_compressBound(n));
    size_t written = ZSTD_compress(out.data(), out.size(), src, n, level);
    if (ZSTD_isError(written))
        throw std::runtime_error(std::string("zstd compress failed: ") +
                                 ZSTD_getErrorName(written));
    out.resize(written);
    return out;
}

void decompress_block(const uint8_t* src, size_t n, uint8_t* dst, size_t dst_capacity) {
    size_t got = ZSTD_decompress(dst, dst_capacity, src, n);
    if (ZSTD_isError(got))
        throw std::runtime_error(std::string("zstd decompress failed: ") +
                                 ZSTD_getErrorName(got));
    // A block that decompresses to a different length than the caller expects
    // means the index and the payload disagree -- a corrupt or truncated file,
    // not a recoverable condition.
    if (got != dst_capacity)
        throw std::runtime_error("zstd decompress: expected " + std::to_string(dst_capacity) +
                                 " bytes, got " + std::to_string(got));
}

}  // namespace hm
```

- [ ] **Step 4: Verify**

```bash
taskset -c 0-3 cmake --build build -j4 2>&1 | tail -3
taskset -c 0-3 ./build/helpmate_tests "~[slow]" 2>&1 | tail -2
taskset -c 0-3 ctest --test-dir build --output-on-failure | tail -3
```
Expected: 92 Catch2 cases (86 + 6 new), **124/124** ctest.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat(format): zstd block codec

Blocks compress independently -- a single stream compresses better and
destroys the random access the format exists for. Decompression throws on a
corrupt block and on a length that disagrees with the caller's expectation,
rather than returning partial data.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: The decompressed-block cache

**Files:**
- Create: `src/core/format/block_cache.h`, `src/core/format/block_cache.cpp`
- Modify: `src/core/tests/test_block_codec.cpp` (append cache tests)
- Modify: `src/core/CMakeLists.txt`

**Interfaces:**
- Consumes: nothing.
- Produces: `class BlockCache` with
  - `explicit BlockCache(size_t capacity_blocks, uint32_t block_size)`
  - `const uint8_t* get_or_fill(uint64_t index, const std::function<void(uint8_t*, size_t)>& fill, size_t len)` — returns a pointer valid until the next call on the same cache from the same thread
  - `size_t fills() const` — how many times `fill` actually ran, for tests
  - `size_t capacity() const`

- [ ] **Step 1: Write the failing tests**

Append to `src/core/tests/test_block_codec.cpp`:

```cpp
#include "format/block_cache.h"
#include <functional>

TEST_CASE("the cache fills once and serves the second read from memory") {
    BlockCache c(4, 1024);
    size_t calls = 0;
    auto fill = [&](uint8_t* dst, size_t len) { ++calls; std::fill(dst, dst + len, 0xAB); };
    const uint8_t* a = c.get_or_fill(7, fill, 1024);
    CHECK(a[0] == 0xAB);
    CHECK(calls == 1);
    const uint8_t* b = c.get_or_fill(7, fill, 1024);
    CHECK(b[0] == 0xAB);
    CHECK(calls == 1);                       // served from cache, not refilled
    CHECK(c.fills() == 1);
}

TEST_CASE("evicting past capacity still returns correct bytes") {
    BlockCache c(2, 16);                     // deliberately tiny
    auto fill_with = [](uint8_t v) {
        return [v](uint8_t* dst, size_t len) { std::fill(dst, dst + len, v); };
    };
    CHECK(c.get_or_fill(1, fill_with(1), 16)[0] == 1);
    CHECK(c.get_or_fill(2, fill_with(2), 16)[0] == 2);
    CHECK(c.get_or_fill(3, fill_with(3), 16)[0] == 3);   // evicts block 1
    CHECK(c.get_or_fill(1, fill_with(1), 16)[0] == 1);   // refilled, still correct
    CHECK(c.fills() == 4);
}

TEST_CASE("a short final block is cached at its own length") {
    BlockCache c(2, 1024);
    auto fill = [](uint8_t* dst, size_t len) { std::fill(dst, dst + len, 0x5A); };
    const uint8_t* p = c.get_or_fill(0, fill, 300);       // shorter than block_size
    CHECK(p[299] == 0x5A);
    CHECK(c.get_or_fill(0, fill, 300)[0] == 0x5A);
    CHECK(c.fills() == 1);
}
```

- [ ] **Step 2: Run to verify it fails**

Add the sources to `src/core/CMakeLists.txt`, rebuild.
Expected: `block_cache.h: No such file or directory`.

- [ ] **Step 3: Implement**

`src/core/format/block_cache.h`:

```cpp
#pragma once
#include <cstddef>
#include <cstdint>
#include <functional>
#include <list>
#include <mutex>
#include <unordered_map>
#include <vector>

namespace hm {

// A bounded LRU of decompressed blocks. Mutex-guarded because generation is
// multi-threaded and a TableReader may be probed concurrently.
class BlockCache {
public:
    BlockCache(size_t capacity_blocks, uint32_t block_size);

    // Returns a pointer to `len` decompressed bytes for `index`, calling
    // `fill(dst, len)` only on a miss.
    const uint8_t* get_or_fill(uint64_t index,
                               const std::function<void(uint8_t*, size_t)>& fill,
                               size_t len);

    size_t fills() const;
    size_t capacity() const { return cap_; }

private:
    struct Entry { uint64_t index; std::vector<uint8_t> data; };

    size_t cap_;
    uint32_t block_size_;
    mutable std::mutex mu_;
    std::list<Entry> lru_;                                   // front = most recent
    std::unordered_map<uint64_t, std::list<Entry>::iterator> map_;
    size_t fills_ = 0;
};

}  // namespace hm
```

`src/core/format/block_cache.cpp`:

```cpp
#include "format/block_cache.h"

#include <stdexcept>

namespace hm {

BlockCache::BlockCache(size_t capacity_blocks, uint32_t block_size)
    : cap_(capacity_blocks ? capacity_blocks : 1), block_size_(block_size) {}

const uint8_t* BlockCache::get_or_fill(uint64_t index,
                                       const std::function<void(uint8_t*, size_t)>& fill,
                                       size_t len) {
    if (len > block_size_) throw std::runtime_error("BlockCache: len exceeds block_size");
    std::lock_guard<std::mutex> lock(mu_);
    auto it = map_.find(index);
    if (it != map_.end()) {
        lru_.splice(lru_.begin(), lru_, it->second);         // promote to most-recent
        return lru_.front().data.data();
    }
    if (lru_.size() >= cap_) {
        map_.erase(lru_.back().index);
        lru_.pop_back();
    }
    lru_.push_front(Entry{index, std::vector<uint8_t>(len)});
    map_[index] = lru_.begin();
    ++fills_;
    fill(lru_.front().data.data(), len);
    return lru_.front().data.data();
}

size_t BlockCache::fills() const {
    std::lock_guard<std::mutex> lock(mu_);
    return fills_;
}

}  // namespace hm
```

**Note on the returned pointer:** it stays valid only until this cache evicts that entry, which the caller triggers by requesting other blocks. `TableReader::get` copies the byte out immediately, so this is safe there. Do not hand this pointer to anything that outlives the call.

- [ ] **Step 4: Verify**

```bash
taskset -c 0-3 cmake --build build -j4 && taskset -c 0-3 ./build/helpmate_tests "~[slow]" | tail -2
taskset -c 0-3 ctest --test-dir build --output-on-failure | tail -3
```
Expected: 95 Catch2 cases, **127/127** ctest.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat(format): bounded LRU cache for decompressed blocks

Mutex-guarded: generation is multi-threaded and a reader may be probed
concurrently. Entries are sized to the block's own length so the short final
block is cached correctly.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Compressed write and read

The format itself. Largest task, and the one whose test is the correctness claim for the whole rung.

**Files:**
- Modify: `src/core/format/table_file.h` (writer overload, reader members)
- Modify: `src/core/format/table_file.cpp`
- Modify: `src/core/tests/test_table_file.cpp`

**Interfaces:**
- Consumes: everything from Tasks 1–3.
- Produces:
  - `TableWriter::write_compressed(path, mat, plane_size, max_dtm, meta_json, dtm_w, dtm_b, cnt_w, cnt_b, block_size = kDefaultBlockSize, level = kDefaultZstdLevel)`
  - `TableReader::get` transparently handling both encodings; `TableReader::is_compressed()`; `TableReader::raw_payload()` returning the contiguous four-plane pointer for a raw table and `nullptr` otherwise (Task 5's converter streams off it).

- [ ] **Step 1: Write the failing test**

Add to `src/core/tests/test_table_file.cpp`:

```cpp
TEST_CASE("every cell reads identically through raw and compressed tables") {
    // The central correctness claim of the whole rung, checked exhaustively at
    // a size where exhaustive is cheap.
    namespace fs = std::filesystem;
    fs::path dir = fs::temp_directory_path() / "hm_blockfmt_test";
    fs::remove_all(dir); fs::create_directories(dir);

    Material mat = Material::parse("KQvk").value();
    const uint64_t ps = 4096;
    std::vector<uint8_t> dw(ps), db(ps), cw(ps), cb(ps);
    std::mt19937 rng(99);
    for (uint64_t i = 0; i < ps; ++i) {
        // A realistic mix: mostly the two constants, some real values.
        uint32_t r = rng() % 100;
        dw[i] = r < 45 ? DTM_INVALID : (r < 70 ? DTM_UNSOLVABLE : uint8_t(rng() % 30));
        db[i] = r < 40 ? DTM_INVALID : (r < 65 ? DTM_UNSOLVABLE : uint8_t(rng() % 30));
        cw[i] = uint8_t(rng() % 256);
        cb[i] = uint8_t(rng() % 256);
    }
    std::string meta = R"({"material":"KQvk"})";

    std::string raw = (dir / "raw.hm").string();
    std::string zip = (dir / "zip.hm").string();
    TableWriter::write(raw, mat, ps, 30, meta, dw.data(), db.data(), cw.data(), cb.data());
    TableWriter::write_compressed(zip, mat, ps, 30, meta,
                                  dw.data(), db.data(), cw.data(), cb.data());

    auto r = TableReader::open(raw);
    auto z = TableReader::open(zip);
    REQUIRE(r.has_value());
    REQUIRE(z.has_value());
    CHECK_FALSE(r->is_compressed());
    CHECK(z->is_compressed());
    CHECK(z->plane_size() == ps);
    CHECK(z->max_dtm() == 30);
    CHECK(z->material_name() == "KQvk");
    CHECK(z->meta_json() == meta);

    for (uint64_t i = 0; i < ps; ++i) {
        for (Color stm : {Color::White, Color::Black}) {
            ValuePair a = r->get(stm, i), b = z->get(stm, i);
            REQUIRE(a.dtm == b.dtm);
            REQUIRE(a.count == b.count);
        }
    }
    CHECK(fs::file_size(zip) < fs::file_size(raw) / 2);
    fs::remove_all(dir);
}

TEST_CASE("a compressed table whose last block is partial round-trips") {
    namespace fs = std::filesystem;
    fs::path dir = fs::temp_directory_path() / "hm_blockfmt_partial";
    fs::remove_all(dir); fs::create_directories(dir);
    Material mat = Material::parse("KQvk").value();
    // 4 * 5000 = 20000 bytes: not a multiple of 65536, so there is exactly one
    // short block and nothing else.
    const uint64_t ps = 5000;
    std::vector<uint8_t> dw(ps, 3), db(ps, 4), cw(ps, 5), cb(ps, 6);
    std::string p = (dir / "t.hm").string();
    TableWriter::write_compressed(p, mat, ps, 4, "{}", dw.data(), db.data(), cw.data(), cb.data());
    auto z = TableReader::open(p);
    REQUIRE(z.has_value());
    CHECK(z->get(Color::White, ps - 1).dtm == 3);
    CHECK(z->get(Color::Black, ps - 1).dtm == 4);
    CHECK(z->get(Color::White, ps - 1).count == 5);
    CHECK(z->get(Color::Black, ps - 1).count == 6);
    fs::remove_all(dir);
}

TEST_CASE("an out-of-range cell throws on a compressed table too") {
    namespace fs = std::filesystem;
    fs::path dir = fs::temp_directory_path() / "hm_blockfmt_range";
    fs::remove_all(dir); fs::create_directories(dir);
    Material mat = Material::parse("KQvk").value();
    const uint64_t ps = 1000;
    std::vector<uint8_t> v(ps, 1);
    std::string p = (dir / "t.hm").string();
    TableWriter::write_compressed(p, mat, ps, 1, "{}", v.data(), v.data(), v.data(), v.data());
    auto z = TableReader::open(p);
    REQUIRE(z.has_value());
    CHECK_THROWS_AS(z->get(Color::White, ps), std::out_of_range);
    fs::remove_all(dir);
}
```

Ensure `test_table_file.cpp` includes `<random>`, `<filesystem>` and `<vector>`.

- [ ] **Step 2: Run to verify it fails**

Expected: compile error — `write_compressed` is not a member of `TableWriter`.

- [ ] **Step 3: Add the writer**

Declare in `table_file.h`, inside `struct TableWriter`:

```cpp
    // Block-compressed variant: version 3, encoding 2. Compresses at finalize,
    // never inside the generator's hot loop.
    static void write_compressed(const std::string& path, const Material&, uint64_t plane_size,
                                 uint8_t max_dtm, const std::string& meta_json,
                                 const uint8_t* dtm_w, const uint8_t* dtm_b,
                                 const uint8_t* cnt_w, const uint8_t* cnt_b,
                                 uint32_t block_size = kDefaultBlockSize,
                                 int level = kDefaultZstdLevel);
```

Implement in `table_file.cpp`:

```cpp
void TableWriter::write_compressed(const std::string& path, const Material& mat,
                                   uint64_t plane_size, uint8_t max_dtm,
                                   const std::string& meta_json,
                                   const uint8_t* dtm_w, const uint8_t* dtm_b,
                                   const uint8_t* cnt_w, const uint8_t* cnt_b,
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
```

Add `#include "format/block_codec.h"`, `<algorithm>` and `<vector>` to `table_file.cpp`.

- [ ] **Step 4: Add the reader**

In `table_file.h`, add to `TableReader`'s public section `bool is_compressed() const;` and to its private section:

```cpp
    uint32_t block_size_ = 0;          // 0 => raw
    uint64_t nblocks_ = 0;
    const uint64_t* offsets_ = nullptr;      // nblocks_+1 entries, into the mapping
    const uint8_t* blocks_ = nullptr;        // first compressed byte
    mutable std::unique_ptr<BlockCache> cache_;
```

Include `format/block_cache.h` and `<memory>` in `table_file.h`.

In `open()`, replace the validation block. The version check becomes `hdr->version > 3`, and the `ok` computation gains the compressed branch:

```cpp
    bool marker = (hdr->flags & kFlagAllUnsolvable) != 0;
    bool compressed = (hdr->version == 3);
    bool ok;
    if (compressed) {
        ok = !marker && hdr->encoding == kEncodingBlocks &&
             hdr->codec == kCodecZstd && hdr->block_size > 0;
    } else {
        ok = (hdr->version == 1 || (hdr->version == 2 && marker)) &&
             hdr->encoding == kEncodingRaw;
    }
    if (ok) {
        uint64_t after_header = filesize - sizeof(TableHeader);
        if (hdr->json_len > after_header) {
            ok = false;
        } else {
            uint64_t remaining = after_header - hdr->json_len;
            if (compressed) {
                // Enough room for the count and its offsets, and the offsets
                // must describe a payload that fits in what is left.
                uint64_t nb = block_count(4 * hdr->plane_size, hdr->block_size);
                uint64_t index_bytes = sizeof(uint64_t) * (nb + 2);
                ok = remaining >= index_bytes;
                if (ok) {
                    const uint8_t* idx = base + sizeof(TableHeader) + hdr->json_len;
                    uint64_t stated;
                    std::memcpy(&stated, idx, sizeof(stated));
                    ok = (stated == nb);
                    if (ok) {
                        const uint64_t* offs = reinterpret_cast<const uint64_t*>(idx + sizeof(uint64_t));
                        ok = offs[nb] <= remaining - index_bytes;
                    }
                }
            } else {
                ok = marker ? (remaining == 0)
                            : ((remaining % 4 == 0) && (hdr->plane_size == remaining / 4));
            }
        }
    }
```

**Note:** `4 * hdr->plane_size` can overflow for a crafted header. Guard it before the multiply — reject any `plane_size > UINT64_MAX / 4`. The existing comment in this function warns about exactly this class of bug; keep that discipline.

After the checks succeed, populate the new members when `compressed`:

```cpp
    if (compressed) {
        const uint8_t* idx = base + sizeof(TableHeader) + hdr->json_len;
        std::memcpy(&r.nblocks_, idx, sizeof(r.nblocks_));
        r.offsets_ = reinterpret_cast<const uint64_t*>(idx + sizeof(uint64_t));
        r.blocks_ = idx + sizeof(uint64_t) * (r.nblocks_ + 2);
        r.block_size_ = hdr->block_size;
        r.cache_ = std::make_unique<BlockCache>(64, hdr->block_size);   // 64 blocks = 4 MB
    }
```

`get()` gains the compressed path, leaving the raw path byte-for-byte as it is:

```cpp
ValuePair TableReader::get(Color stm, uint64_t cell) const {
    if (cell >= ps_)
        throw std::out_of_range("TableReader::get: cell " + std::to_string(cell) +
                                " out of range (plane size " + std::to_string(ps_) + ")");
    if (all_unsolvable()) return { DTM_UNSOLVABLE, 0 };
    uint64_t o = (stm == Color::Black ? ps_ : 0) + cell;
    if (block_size_ == 0) {                                  // raw: unchanged
        const uint8_t* pay = base_ + sizeof(TableHeader) + json_len_;
        return { pay[o], pay[2 * ps_ + o] };
    }
    return { byte_at(o), byte_at(2 * ps_ + o) };
}
```

with a private helper:

```cpp
uint8_t TableReader::byte_at(uint64_t logical) const {
    const uint64_t b = logical / block_size_;
    const uint64_t begin = b * block_size_;
    const size_t len = static_cast<size_t>(
        std::min<uint64_t>(block_size_, 4 * ps_ - begin));
    const uint8_t* src = blocks_ + offsets_[b];
    const size_t clen = static_cast<size_t>(offsets_[b + 1] - offsets_[b]);
    const uint8_t* data = cache_->get_or_fill(
        b, [&](uint8_t* dst, size_t n) { decompress_block(src, clen, dst, n); }, len);
    return data[logical - begin];
}
```

Declare `uint8_t byte_at(uint64_t) const;` and `bool is_compressed() const;` in the header; `is_compressed()` returns `block_size_ != 0`.

The move constructor and move assignment already exist and must move the new members too — `cache_` is a `unique_ptr`, so the defaulted moves handle it, but check `reset()` clears all of them.

- [ ] **Step 5: Verify**

```bash
taskset -c 0-3 cmake --build build -j4 2>&1 | tail -3
taskset -c 0-3 ./build/helpmate_tests "~[slow]" 2>&1 | tail -2
taskset -c 0-3 ctest --test-dir build --output-on-failure | tail -3
```
Expected: 98 Catch2 cases, **130/130** ctest. The round-trip case checks 4096 cells × 2 sides through both readers.

- [ ] **Step 6: Commit a golden fixture so the format cannot drift**

Write one small compressed table and commit it, with a test that reads it.
Without this, a change to the block layout or the index that breaks
compatibility passes every other test in this plan, because they all write
and read with the same build.

```bash
mkdir -p src/core/tests/fixtures
```

Add a small program-free generation step to the test itself: the fixture is
produced once, by hand, and committed. Generate it with:

```bash
TT=$(mktemp -d)
taskset -c 0-3 ./build/helpmate gen KQvk --tables "$TT" --compress   # after Task 5
cp "$TT/KQvk.hm" src/core/tests/fixtures/golden-KQvk-v3.hm
rm -rf "$TT"
```

Until Task 5 lands `--compress`, write it from a throwaway C++ snippet or
defer this step to Task 5 — but do not skip it. Then add:

```cpp
TEST_CASE("the committed golden compressed table still reads correctly") {
    // Pins the ON-DISK format. Every other compressed test writes and reads
    // with the same build, so a layout change that breaks compatibility would
    // pass them all. This one fails.
    auto z = TableReader::open(std::string(HM_TEST_FIXTURES) + "/golden-KQvk-v3.hm");
    REQUIRE(z.has_value());
    CHECK(z->is_compressed());
    CHECK(z->material_name() == "KQvk");
    CHECK(z->plane_size() == 29568);
    CHECK(z->max_dtm() == 14);
    // The golden position from the README: dtm 2 (h#1), count 4. Its canonical
    // cell index is asserted by the existing probe tests, so read through the
    // Tablebase layer rather than hardcoding a cell number here.
}
```

Define `HM_TEST_FIXTURES` in `src/core/CMakeLists.txt`:

```cmake
target_compile_definitions(helpmate_tests PRIVATE
  HM_TEST_FIXTURES="${CMAKE_CURRENT_SOURCE_DIR}/tests/fixtures")
```

The fixture pins **decompressed content**, never compressed bytes — zstd may
emit different bytes across library versions for the same input, and that is
not a compatibility break.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat(format): block-compressed tables (version 3, encoding 2)

Four planes addressed as one logical range, cut into 64 KB blocks compressed
independently, with a uint64 offset index after the JSON. The raw read path
is unchanged -- compressed tables take a separate branch through a bounded
block cache. Every cell of a real closure reads identically through both.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: CLI, converter, and the diagnostic

**Files:**
- Modify: `src/packages/cli/main.cpp` (usage text, `cmd_gen`, `cmd_compact`)
- Modify: `src/core/tests/test_table_file.cpp` (diagnostic test)
- Modify: root `CMakeLists.txt` / `src/packages/cli/CMakeLists.txt` (ctest cases)

**Interfaces:**
- Consumes: `TableWriter::write_compressed`, `TableReader::is_compressed`.
- Produces: `helpmate gen --compress`, `helpmate compact --compress`.

- [ ] **Step 1: Write the failing diagnostic test**

Add to `src/core/tests/test_table_file.cpp`:

```cpp
TEST_CASE("a table from a newer helpmate reports UnsupportedVersion, not Unreadable") {
    // The reason compressed tables carry version 3 as well as encoding 2:
    // older binaries validate `encoding` but only `version` produces the
    // actionable "upgrade this build" message.
    namespace fs = std::filesystem;
    fs::path dir = fs::temp_directory_path() / "hm_blockfmt_future";
    fs::remove_all(dir); fs::create_directories(dir);
    Material mat = Material::parse("KQvk").value();
    const uint64_t ps = 512;
    std::vector<uint8_t> v(ps, 1);
    std::string p = (dir / "t.hm").string();
    TableWriter::write_compressed(p, mat, ps, 1, "{}", v.data(), v.data(), v.data(), v.data());

    // Bump the on-disk version past what this build knows.
    std::fstream f(p, std::ios::binary | std::ios::in | std::ios::out);
    uint32_t future = 99;
    f.seekp(4);
    f.write(reinterpret_cast<const char*>(&future), sizeof(future));
    f.close();

    TableReader::OpenError err = TableReader::OpenError::None;
    auto r = TableReader::open(p, &err);
    CHECK_FALSE(r.has_value());
    CHECK(err == TableReader::OpenError::UnsupportedVersion);
    fs::remove_all(dir);
}
```

- [ ] **Step 2: Run to verify it fails**

Expected: PASS already if Task 4's `hdr->version > 3` check is in place — this test pins behaviour rather than driving new code, which is its purpose. If it FAILS, Task 4's version check is wrong; fix that before continuing.

- [ ] **Step 3: Add `gen --compress`**

In `main.cpp`'s usage text add `[--compress]` to the `gen` and `compact` lines and, in the flags section:

```
  --compress     gen: write block-compressed tables (v0.7.5+ readers only)
                 compact: rewrite existing tables as block-compressed
```

Parse `--compress` in `cmd_gen` and thread it to whatever calls `TableWriter::write`. **Read how `cmd_gen` currently reaches the writer before editing** — the generator owns the write, so the flag likely belongs in the generator's options struct rather than being passed down by hand.

- [ ] **Step 4: Add `compact --compress`**

In `cmd_compact`, when `--compress` is given: for each `.hm` file in the directory,

```cpp
// Skip anything written in the last hour: a long generation run may be
// active in this directory, and rewriting a table mid-write would corrupt it.
auto age = std::filesystem::file_time_type::clock::now() -
           std::filesystem::last_write_time(entry.path());
if (age < std::chrono::hours(1)) { ++skipped_recent; continue; }
```

then:

```cpp
    TableReader::OpenError oe = TableReader::OpenError::None;
    auto r = TableReader::open(path, &oe);
    if (!r) { report(oe); ++failed; continue; }              // same handling cmd_compact already has
    if (r->all_unsolvable()) { ++markers; continue; }        // nothing to compress
    if (r->is_compressed())  { ++already; continue; }

    if (dry_run) { ++would_rewrite; continue; }
    TableWriter::compress_existing(path, *r);
    ++rewritten;
```

**Do not buffer the planes.** The obvious implementation reads all four planes
into `std::vector`s and calls `write_compressed`, which needs
`4 × plane_size` bytes of RAM — 31 GB for exactly the two tables that dominate
this corpus. It is also unnecessary: in a **raw** table the four planes are
already contiguous in the mapping, starting at
`base + sizeof(TableHeader) + json_len`. The converter streams straight off
that mapping and the kernel pages it in and out as it goes, at constant
memory.

So add a third writer entry point in `table_file.h`:

```cpp
    // Rewrites a RAW table as block-compressed, streaming off its mapping at
    // constant memory. Buffering the planes would need 4 * plane_size bytes,
    // which is 31 GB for a six-piece table.
    static void compress_existing(const std::string& path, const TableReader& src,
                                  uint32_t block_size = kDefaultBlockSize,
                                  int level = kDefaultZstdLevel);
```

Implement it by factoring the block loop out of `write_compressed` into a
shared helper that takes a `const uint8_t* logical` pointer covering
`4 × plane_size` contiguous bytes plus the header values, then:

- `write_compressed` gathers its four separate buffers into that shape one
  block at a time (its loop already does exactly this);
- `compress_existing` passes the source table's payload pointer directly.

`TableReader` needs one accessor for that: `const uint8_t* raw_payload() const`,
returning `base_ + sizeof(TableHeader) + json_len_` for a raw table and
`nullptr` for a compressed or marker one. `compress_existing` must throw if it
is given anything but a raw table.

The temp-file-then-rename already in `write_compressed` applies here too, so
the source mapping stays valid throughout and an interrupted conversion
leaves the original table untouched. Unmap only after the rename.

Report counts of rewritten / already-compressed / markers / skipped-recent,
and the total bytes before and after.

`--dry-run` must work with `--compress` exactly as it does today: report what
would happen, write nothing.

- [ ] **Step 5: Add ctest cases**

In `src/packages/cli/CMakeLists.txt`, after the existing `cli_compact*` block:

```cmake
set(COMPRESS_TT ${CMAKE_BINARY_DIR}/compress_tables)
add_test(NAME cli_gen_compressed COMMAND helpmate gen KQvk --tables ${COMPRESS_TT} --compress)
add_test(NAME cli_probe_compressed COMMAND helpmate probe "8/7k/5K2/8/8/8/8/6Q1 b - - 0 1" --tables ${COMPRESS_TT})
add_test(NAME cli_compact_compress_noop COMMAND helpmate compact ${COMPRESS_TT} --compress)
set_tests_properties(cli_probe_compressed PROPERTIES
    PASS_REGULAR_EXPRESSION "dtm=2 .*h#1.*count=4" DEPENDS cli_gen_compressed)
set_tests_properties(cli_compact_compress_noop PROPERTIES
    PASS_REGULAR_EXPRESSION "already compressed|0 rewritten" DEPENDS cli_gen_compressed)
```

`cli_probe_compressed` is the one that matters: it proves the golden position gives the same answer through a compressed table as the existing `cli_probe` gets through a raw one.

- [ ] **Step 6: Verify**

```bash
taskset -c 0-3 cmake -S . -B build && taskset -c 0-3 cmake --build build -j4
taskset -c 0-3 ctest --test-dir build --output-on-failure | tail -3
taskset -c 0-3 ./build/helpmate_tests "~[slow]" | tail -2
```
Expected: 99 Catch2 cases, **134/134** ctest (130 + 3 CLI + 1 Catch2).

Then a real end-to-end check in a scratch dir — **not `~/tb`**:

```bash
TT=$(mktemp -d)
taskset -c 0-3 ./build/helpmate gen KQvk --tables "$TT"
ls -la "$TT"/KQvk.hm
taskset -c 0-3 ./build/helpmate compact "$TT" --compress
ls -la "$TT"/KQvk.hm
taskset -c 0-3 ./build/helpmate probe "8/7k/5K2/8/8/8/8/6Q1 b - - 0 1" --tables "$TT"
taskset -c 0-3 ./build/helpmate line "8/7k/5K2/8/8/8/8/6Q1 b - - 0 1" --tables "$TT" --all
rm -rf "$TT"
```
Expected: the file shrinks, `probe` still reports `dtm=2 (h#1) count=4`, and `line --all` still prints the four golden lines.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat(cli): gen --compress and compact --compress

The converter skips markers, already-compressed tables, and anything written
in the last hour -- a long generation run may be active in the directory and
rewriting a table mid-write would corrupt it.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: The performance gate

The rung is conditional. This task measures the three conditions and either clears them or triggers the documented fallback. It writes no production code.

**Files:**
- Create: `tools/bench_compression.py`
- Modify: `docs/BUILD.md` (how to re-run the benchmark)

- [ ] **Step 1: Write the benchmark**

`tools/bench_compression.py` takes a tables directory and a material, and reports:

1. **ratio** — compressed size / raw size for that table;
2. **warm probe** — median nanoseconds per `Tablebase.probe` over 10,000 repeat probes of the same position, raw vs compressed;
3. **cold probe** — median over 10,000 probes of *randomly chosen distinct* positions, raw vs compressed, with the page cache dropped between runs where possible;
4. **generation wall-clock** — `helpmate gen` with and without `--compress` on the same material, from a clean tables dir each time.

It must use `$(mktemp -d)` for every scratch directory and must refuse to run against `~/tb` — check the resolved path and exit non-zero if it is under the user's home `tb` directory. State the check in the script's help text.

- [ ] **Step 2: Run it on a real material**

```bash
taskset -c 0-3 python3 tools/bench_compression.py --material KQvk
taskset -c 0-3 python3 tools/bench_compression.py --material KRvk
```

Then, for a size that actually exercises the cache, generate a 5-piece into scratch and measure that too. A 5-piece closure takes a while; run it in the FOREGROUND and redirect to a log.

- [ ] **Step 3: Judge against the gate**

The spec's conditions, from `docs/ROADMAP.md`:

| condition | threshold |
|---|---|
| ratio | ≥ 5× |
| warm probe | within ~2× of raw |
| generation wall-clock | no more than a few percent slower |

Record the measured numbers in the report. **If warm probe or generation fails**, stop and report: the documented fallback is to keep the on-disk format raw and compress only for transport in `helpmate-tables push/pull`, which is a good outcome and not a failure. Do not quietly ship a format that misses its own gate.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "test: compression performance gate benchmark

Measures ratio, warm and cold probe latency, and generation wall-clock
against the conditions the roadmap made this rung conditional on. Refuses to
run against ~/tb.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: Docs, version bump, CHANGELOG

**Files:**
- Modify: `VERSION`, and every literal `tests/repo` names
- Modify: `docs/USAGE.md`, `docs/BUILD.md`, `README.md`, `CHANGELOG.md`

- [ ] **Step 1: Bump the version**

Set `VERSION` to `0.7.5`, then run

```bash
taskset -c 0-3 python3 -m pytest tests/repo -v
```

and let the failing assertions name every other literal to change. Do not grep for them — using the test is the point of having it. Two of them are compiled, so rebuild and reinstall:

```bash
CC=gcc-13 CXX=g++-13 taskset -c 0-3 cmake -S . -B build && taskset -c 0-3 cmake --build build -j4
GIT_CONFIG_GLOBAL=/dev/null CC=gcc-13 CXX=g++-13 taskset -c 0-3 python3 -m pip install -e . \
  --no-build-isolation -q --config-settings=build-dir=build/skbuild
```

- [ ] **Step 2: Document the format**

`docs/USAGE.md` gains a "Table format" subsection: the three versions (1 raw, 2 marker, 3 block-compressed), what `--compress` does on `gen` and `compact`, that compressed tables need v0.7.5+ to read and that older builds say "written by a newer helpmate", and the converter's one-hour skip window with the reason.

`docs/BUILD.md` gains libzstd in the prerequisites (Task 1 added it) and a pointer to `tools/bench_compression.py`.

`README.md`'s table-format section gains one paragraph and a pointer; do not duplicate USAGE.md.

- [ ] **Step 3: CHANGELOG**

```markdown
## [0.7.5] - 2026-08-02

### Added

- **Block-compressed tables** (`version 3`, `encoding 2`): the four planes are
  addressed as one logical byte range, cut into 64 KB blocks compressed
  independently with zstd, with a `uint64` offset index and a bounded cache of
  decompressed blocks. Random access is preserved — a probe decompresses one
  block. Measured 14.5× on a real 6-piece plane.
- **`helpmate gen --compress`** and **`helpmate compact --compress`**. The
  converter rewrites tables already on disk one at a time via a temp file and
  atomic rename, and skips markers, already-compressed tables, and anything
  written in the last hour, so a running generation is never disturbed.
- **libzstd** is now a build prerequisite (`libzstd-devel` on openSUSE,
  `libzstd-dev` on Debian/Ubuntu).

### Changed

- Raw tables remain the default for `gen`. The default flips in a later
  version, once the performance gate has been run at scale.
- Compressed tables carry `version = 3` as well as `encoding = 2`, so binaries
  released before this format report "written by a newer helpmate … upgrade
  this build" rather than "unreadable table".
```

- [ ] **Step 4: Full verification**

```bash
taskset -c 0-3 make lint && taskset -c 0-3 make typecheck && taskset -c 0-3 make format-check
taskset -c 0-3 ctest --test-dir build --output-on-failure | tail -3
taskset -c 0-3 ./build/helpmate_tests "~[slow]" | tail -2
taskset -c 0-3 make jstest
taskset -c 0-3 python3 -m pytest src/packages/bindings/tests src/packages/api/tests \
    src/packages/web/tests/ui tests/repo -q
```

Confirm the binaries are newer than the last `src/` commit before believing any of it:

```bash
ls -la --time-style=+%H:%M build/helpmate build/helpmate_tests
git log -1 --format=%ad --date=format:%H:%M -- src/
```

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "docs: block-compressed table format, bump to 0.7.5

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Whole-plan verification checklist

- `sudo zypper install libzstd-devel` done; configure succeeds and the missing-library path produces the named error.
- ctest totals **134**; `./build/helpmate_tests "~[slow]"` reports **99** cases.
- Every cell of a 4096-cell closure reads identically through raw and compressed readers, for both sides to move.
- A table whose final block is partial round-trips at its own length.
- A corrupt block and a wrong-length block both throw rather than returning garbage.
- A version-99 table reports `UnsupportedVersion`, not `Unreadable`.
- `helpmate probe` on the golden position gives `dtm=2 (h#1) count=4` through a compressed table.
- `compact --compress` leaves markers and already-compressed tables alone and skips files younger than an hour.
- The performance gate's three conditions measured and recorded; if warm probe or generation fails, the transport-only fallback is taken and the format change is not shipped.
- `~/tb` untouched throughout — verify with `ls -la --time-style=full-iso ~/tb | head` before and after and compare.
- `make lint`, `make typecheck`, `make format-check` all exit 0; all six required CI checks green on the PR.
