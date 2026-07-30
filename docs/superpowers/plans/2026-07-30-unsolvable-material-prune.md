# Unsolvable-Material Prune (v0.6.1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Never generate or store a material that provably cannot contain a helpmate, and reclaim the ~34 GB of all-unsolvable tables already on disk — spec: `docs/superpowers/specs/2026-07-30-unsolvable-material-prune-design.md`.

**Architecture:** Three layers. (1) `Material::mating_side_is_bare_king()` — a free structural test. (2) A solvability decision in `generate()`: bare king → unsolvable; else if every direct successor is already unsolvable, run a plane-free mate scan, and if it finds no mate the slice is unsolvable. (3) A marker `.hm` variant (header flag, empty payload) that readers expand to `DTM_UNSOLVABLE` for every cell, plus `helpmate compact` to convert existing full tables.

**Tech Stack:** C++20 (GCC 13), CMake, Catch2. No new dependencies. One Python change (`server/helpmate_server/tables_cli.py`).

## Global Constraints

- **Pruning must never change a solvable slice.** Equivalence tests compare pruned vs `--no-prune` output; for a solvable material the file must be byte-identical.
- **Format compatibility:** ordinary tables keep `version = 1`; only marker tables are written with `version = 2`. `TableReader::open` must accept both. Existing tables and existing consumers stay valid.
- Marker table = `TableHeader` + metadata JSON + **zero** payload bytes, `max_dtm = DTM_UNSOLVABLE`, `flags` bit 0 set. `plane_size` and `material` stay populated so the v0.5.0 load-time identity checks still work.
- `TableReader::get` on a marker returns `{DTM_UNSOLVABLE, 0}` for `cell < plane_size()`, and still throws `std::out_of_range` for `cell >= plane_size()`.
- Known unsolvable classes are **test oracles only**, never generator logic: `Kvk*`; `KBvk[qr]*`; `KNvk[q]*`. Known-solvable counter-oracles: `KNvkr`, `KNvkqr`, `KBvkrb`, `KBvkqb`, `KBvkb`, `KBvkn`, `KBvkp`, `KNvkb`, `KNvkn`, `KNvkp`, `KNvkbb`.
- Build env: `PATH="$HOME/.local/bin:$PATH"`, `CXX=/usr/bin/g++-13 CC=/usr/bin/gcc-13`; build dir `build/` is already configured — `cmake --build build -j4`. Never let CMake FetchContent clone (SSH passphrase); if a reconfigure is unavoidable use `-DFETCHCONTENT_FULLY_DISCONNECTED=ON` plus `FETCHCONTENT_SOURCE_DIR_{CHESSMG,CATCH2,JSON}=$PWD/build/_deps/*-src`.
- All tests under `taskset -c 0-3` (4-core cap). A large 6-piece generation may be running: never write into `~/tb`, use scratch dirs.
- Commits are local; message ends with the trailer line exactly: `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.

---

### Task 1: `Material::mating_side_is_bare_king()`

**Files:**
- Modify: `src/indexing/material.h` (add declaration after `pawn_count()`), `src/indexing/material.cpp`
- Test: `tests/cpp/test_material.cpp` (append)

**Interfaces:**
- Produces: `bool Material::mating_side_is_bare_king() const` — true iff the white side holds no piece other than the king.

- [ ] **Step 1: Write the failing test**

Append to `tests/cpp/test_material.cpp`:

```cpp
TEST_CASE("mating_side_is_bare_king identifies materials white can never mate with") {
    auto bare = [](const char* n) {
        return Material::parse(n)->mating_side_is_bare_king();
    };
    // White is a bare king: it can never give check, so no mate can exist.
    CHECK(bare("Kvk"));
    CHECK(bare("Kvkq"));
    CHECK(bare("Kvkqrp"));      // black may promote; white stays a bare king
    // White has material: not this rule's business (solvability decided elsewhere).
    CHECK_FALSE(bare("KQvk"));
    CHECK_FALSE(bare("KBvkqqr"));
    CHECK_FALSE(bare("KPvk"));  // a white pawn can promote
}
```

- [ ] **Step 2: Run it**

`PATH="$HOME/.local/bin:$PATH" cmake --build build -j4` → FAILS to compile: `'const struct hm::Material' has no member named 'mating_side_is_bare_king'`.

- [ ] **Step 3: Implement**

In `src/indexing/material.h`, directly after the `int pawn_count() const;` line:

```cpp
    // True iff the white (mating) side holds only its king. Such a side can
    // never give check, so the material can contain no mate — and since only
    // black owns pawns here, no promotion can change that.
    bool mating_side_is_bare_king() const;
```

In `src/indexing/material.cpp`, next to the other small accessors:

```cpp
bool Material::mating_side_is_bare_king() const {
    for (size_t i = 0; i < white.size(); ++i)
        if (i != (size_t)PieceType::King && white[i] != 0) return false;
    return true;
}
```

(`PieceType::King == 0`, per `src/chess/types.h:10`; `material.cpp` already includes `chess/types.h` transitively through `material.h`.)

- [ ] **Step 4: Run it**

`PATH="$HOME/.local/bin:$PATH" cmake --build build -j4 && taskset -c 0-3 ./build/helpmate_tests "mating_side_is_bare_king*" -v high` → PASS, 6 assertions.

- [ ] **Step 5: Commit**

```bash
git add src/indexing/material.h src/indexing/material.cpp tests/cpp/test_material.cpp
git commit   # feat: Material::mating_side_is_bare_king
```

---

### Task 2: Marker tables in the file format

**Files:**
- Modify: `src/format/table_file.h` (header struct + writer/reader declarations), `src/format/table_file.cpp`
- Test: `tests/cpp/test_table_file.cpp` (append)

**Interfaces:**
- Consumes: existing `TableHeader`, `TableWriter::write`, `TableReader::open/get/plane_size/max_dtm/material_name/meta_json`.
- Produces:
  - `TableHeader.reserved[15]` is replaced by `uint8_t flags; uint8_t reserved[14];` — `flags` bit `0x01` = all-unsolvable marker. `sizeof(TableHeader)` stays 64 (the `static_assert` must still hold).
  - `static void TableWriter::write_unsolvable(const std::string& path, const Material& mat, uint64_t plane_size, const std::string& meta_json);`
  - `bool TableReader::all_unsolvable() const;`

- [ ] **Step 1: Write the failing test**

Append to `tests/cpp/test_table_file.cpp` (match the file's existing temp-dir helper; if it uses a `unique_tmp_dir()` helper, use that instead of the literal below):

```cpp
TEST_CASE("marker tables expand to DTM_UNSOLVABLE without a payload") {
    namespace fs = std::filesystem;
    fs::path dir = fs::temp_directory_path() /
                   ("hm_marker_" + std::to_string(::getpid()));
    fs::create_directories(dir);
    std::string path = (dir / "KBvkq.hm").string();
    Material m = *Material::parse("KBvkq");
    const uint64_t ps = 1234;

    TableWriter::write_unsolvable(path, m, ps, R"({"material":"KBvkq"})");

    // A marker is tiny: header + JSON, no planes.
    CHECK(fs::file_size(path) < 512);

    auto r = TableReader::open(path);
    REQUIRE(r.has_value());
    CHECK(r->all_unsolvable());
    CHECK(r->plane_size() == ps);
    CHECK(r->material_name() == "KBvkq");
    CHECK(r->max_dtm() == DTM_UNSOLVABLE);
    for (uint64_t c : {uint64_t(0), ps / 2, ps - 1}) {
        auto v = r->get(Color::White, c);
        CHECK(v.dtm == DTM_UNSOLVABLE);
        CHECK(v.count == 0);
        CHECK(r->get(Color::Black, c).dtm == DTM_UNSOLVABLE);
    }
    CHECK_THROWS_AS(r->get(Color::White, ps), std::out_of_range);
    CHECK_THROWS_AS(r->get(Color::White, ~uint64_t(0)), std::out_of_range);
    fs::remove_all(dir);
}

TEST_CASE("ordinary tables stay format version 1 and keep reading") {
    namespace fs = std::filesystem;
    fs::path dir = fs::temp_directory_path() /
                   ("hm_v1_" + std::to_string(::getpid()));
    fs::create_directories(dir);
    std::string path = (dir / "Kvk.hm").string();
    std::vector<uint8_t> dw(4, 7), db(4, 8), cw(4, 1), cb(4, 2);
    TableWriter::write(path, *Material::parse("Kvk"), 4, 7, "{}",
                       dw.data(), db.data(), cw.data(), cb.data());

    std::ifstream in(path, std::ios::binary);
    TableHeader hdr{};
    in.read(reinterpret_cast<char*>(&hdr), sizeof(hdr));
    CHECK(hdr.version == 1);
    CHECK((hdr.flags & 0x01) == 0);

    auto r = TableReader::open(path);
    REQUIRE(r.has_value());
    CHECK_FALSE(r->all_unsolvable());
    CHECK(r->get(Color::White, 0).dtm == 7);
    CHECK(r->get(Color::Black, 3).dtm == 8);
    fs::remove_all(dir);
}
```

- [ ] **Step 2: Run it**

`PATH="$HOME/.local/bin:$PATH" cmake --build build -j4` → FAILS: no member `write_unsolvable` / `all_unsolvable` / `flags`.

- [ ] **Step 3: Implement**

`src/format/table_file.h` — in `TableHeader`, replace `uint8_t reserved[15];` with:

```cpp
    uint8_t flags;            // bit 0: all-unsolvable marker (no payload follows)
    uint8_t reserved[14];
```

Add to the `TableWriter` struct:

```cpp
    // Marker table: header + JSON, no planes. Every cell reads as
    // DTM_UNSOLVABLE. Written with version 2; ordinary tables stay version 1.
    static void write_unsolvable(const std::string& path, const Material&,
                                 uint64_t plane_size, const std::string& meta_json);
```

Add to `TableReader`'s public section:

```cpp
    bool all_unsolvable() const;
```

`src/format/table_file.cpp`:

```cpp
constexpr uint8_t kFlagAllUnsolvable = 0x01;

void TableWriter::write_unsolvable(const std::string& path, const Material& mat,
                                   uint64_t plane_size, const std::string& meta_json) {
    TableHeader hdr{};
    std::memcpy(hdr.magic, "HM8P", 4);
    hdr.version = 2;                       // marker tables only
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

    std::string tmp = path + ".tmp";
    {
        std::ofstream out(tmp, std::ios::binary | std::ios::trunc);
        out.write(reinterpret_cast<const char*>(&hdr), sizeof(hdr));
        out.write(meta_json.data(), (std::streamsize)meta_json.size());
        if (!out) throw std::runtime_error("write_unsolvable: failed writing " + tmp);
    }
    std::filesystem::rename(tmp, path);
}

bool TableReader::all_unsolvable() const {
    return (reinterpret_cast<const TableHeader*>(base_)->flags & kFlagAllUnsolvable) != 0;
}
```

In `TableReader::open`, the validation currently requires `hdr->version == 1` and a payload of `4 * plane_size`. Change it so a marker is accepted and a normal table is validated exactly as before:

```cpp
    bool marker = (hdr->flags & kFlagAllUnsolvable) != 0;
    bool ok = std::memcmp(hdr->magic, "HM8P", 4) == 0 &&
              (hdr->version == 1 || (hdr->version == 2 && marker)) &&
              hdr->encoding == 1;
    if (ok) {
        if (hdr->json_len > after_header) {
            ok = false;
        } else {
            uint64_t remaining = after_header - hdr->json_len;
            ok = marker ? (remaining == 0)
                        : ((remaining % 4 == 0) && (hdr->plane_size == remaining / 4));
        }
    }
```

In `TableReader::get`, return the synthetic value before touching the payload — keep the existing range check first:

```cpp
    if (cell >= ps_)
        throw std::out_of_range(/* ...existing message... */);
    if (all_unsolvable()) return { DTM_UNSOLVABLE, 0 };
```

- [ ] **Step 4: Run it**

```
PATH="$HOME/.local/bin:$PATH" cmake --build build -j4
taskset -c 0-3 ./build/helpmate_tests "marker tables*"
taskset -c 0-3 ./build/helpmate_tests "ordinary tables*"
taskset -c 0-3 ./build/helpmate_tests            # whole fast suite, must stay green
```
Expected: all pass. The full suite matters here — every existing table test exercises the modified `open`.

- [ ] **Step 5: Commit**

```bash
git add src/format/table_file.h src/format/table_file.cpp tests/cpp/test_table_file.cpp
git commit   # feat: all-unsolvable marker tables (format v2, no payload)
```

---

### Task 3: Plane-free mate scan

**Files:**
- Modify: `src/generator/generator.h` (declaration), `src/generator/generator.cpp`
- Test: `tests/cpp/test_generator_prune.cpp` (create), `CMakeLists.txt:50` (add to `helpmate_tests` sources)

**Interfaces:**
- Consumes: `SliceIndex`, `Board`, `PosState::Checkmate` (see `init_pass` in `src/generator/generator.cpp` for the exact idiom: decode cell → `b.reset(pp, stm)` → skip if `b.opponent_in_check()` → `b.state() == PosState::Checkmate`).
- Produces: `bool slice_has_any_mate(const Material& m);` declared in `src/generator/generator.h` in namespace `hm`. Allocates no planes; returns as soon as one mate is found.

- [ ] **Step 1: Write the failing test**

Create `tests/cpp/test_generator_prune.cpp`:

```cpp
#include "generator/generator.h"
#include "indexing/material.h"
#include <catch2/catch_test_macros.hpp>

using namespace hm;

TEST_CASE("slice_has_any_mate finds mates only where they exist") {
    // KQvk: the queen mates the bare king cooperatively — mates exist.
    CHECK(slice_has_any_mate(*Material::parse("KQvk")));
    // Bare white king cannot even give check.
    CHECK_FALSE(slice_has_any_mate(*Material::parse("Kvk")));
    CHECK_FALSE(slice_has_any_mate(*Material::parse("Kvkq")));
    // King+bishop against king+queen: a queen on the blocking square can always
    // interpose or capture, so no mate position exists (user's KBvk[qr]* class).
    CHECK_FALSE(slice_has_any_mate(*Material::parse("KBvkq")));
    // King+knight against king+bishop does have mates (KNvkb is solvable).
    CHECK(slice_has_any_mate(*Material::parse("KNvkb")));
}
```

Add `tests/cpp/test_generator_prune.cpp` to the `add_executable(helpmate_tests ...)` list in `CMakeLists.txt` (line 50), keeping the existing one-line style.

- [ ] **Step 2: Run it**

`PATH="$HOME/.local/bin:$PATH" cmake --build build -j4` → FAILS: `'slice_has_any_mate' was not declared in this scope`.

- [ ] **Step 3: Implement**

Declare in `src/generator/generator.h`, next to `generate()`:

```cpp
// True iff any position in this slice is checkmate (black to move, mated).
// Allocates no value planes: it is the cheap half of init_pass, used to decide
// whether a slice can be pruned before committing to its RAM.
bool slice_has_any_mate(const Material& m);
```

Implement in `src/generator/generator.cpp` (mirror `init_pass`'s decode/legality idiom — read it first and match it exactly):

```cpp
bool slice_has_any_mate(const Material& m) {
    SliceIndex idx(m);
    std::vector<PlacedPiece> pp;
    Board b;
    uint64_t n = idx.size();
    for (uint64_t c = 0; c < n; ++c) {
        if (!idx.decode(c, pp)) continue;
        auto e = idx.encode(pp);
        if (!e || *e != c) continue;                    // non-canonical duplicate
        b.reset(pp, Color::Black);                      // mates are black-to-move
        if (b.opponent_in_check()) continue;            // illegal for this stm
        if (b.state() == PosState::Checkmate) return true;
    }
    return false;
}
```

- [ ] **Step 4: Run it**

```
PATH="$HOME/.local/bin:$PATH" cmake --build build -j4
taskset -c 0-3 ./build/helpmate_tests "slice_has_any_mate*"
```
Expected: PASS. (`KBvkq` is 462·64³ ≈ 121 M cells — the scan takes tens of seconds. If it exceeds ~2 minutes, report it: the tag `[slow]` may be warranted, which is a plan decision, not yours to make silently.)

- [ ] **Step 5: Commit**

```bash
git add src/generator/generator.h src/generator/generator.cpp tests/cpp/test_generator_prune.cpp CMakeLists.txt
git commit   # feat: plane-free mate scan for prune decisions
```

---

### Task 4: Prune decision in `generate()`

**Files:**
- Modify: `src/generator/generator.h` (`GenOptions`), `src/generator/generator.cpp` (`generate()` loop, ~lines 349-379)
- Test: `tests/cpp/test_generator_prune.cpp` (append)

**Interfaces:**
- Consumes: `Material::mating_side_is_bare_king()` (Task 1), `TableWriter::write_unsolvable` + `TableReader::all_unsolvable()` (Task 2), `slice_has_any_mate()` (Task 3).
- Produces: `GenOptions.prune` (default `true`); `generate()` writes a marker table instead of generating whenever the slice is provably unsolvable.

- [ ] **Step 1: Write the failing test**

Append to `tests/cpp/test_generator_prune.cpp`:

```cpp
#include "format/table_file.h"
#include <filesystem>
#include <fstream>

TEST_CASE("generate prunes provably unsolvable slices") {
    namespace fs = std::filesystem;
    fs::path dir = fs::temp_directory_path() /
                   ("hm_prune_" + std::to_string(::getpid()));
    fs::remove_all(dir);
    GenOptions opt;
    opt.tables_dir = dir.string();
    opt.threads = 2;

    generate(*Material::parse("Kvkq"), opt);            // whole closure: Kvk, Kvkq

    for (const char* n : {"Kvk", "Kvkq"}) {
        auto r = TableReader::open((dir / (std::string(n) + ".hm")).string());
        REQUIRE(r.has_value());
        INFO("slice " << n);
        CHECK(r->all_unsolvable());                     // bare king: pruned structurally
        CHECK(fs::file_size((dir / (std::string(n) + ".hm")).string()) < 4096);
        CHECK(r->get(Color::White, 0).dtm == DTM_UNSOLVABLE);
    }
    fs::remove_all(dir);
}

TEST_CASE("generate leaves solvable slices byte-identical when pruning") {
    namespace fs = std::filesystem;
    fs::path a = fs::temp_directory_path() / ("hm_pr_on_" + std::to_string(::getpid()));
    fs::path b = fs::temp_directory_path() / ("hm_pr_off_" + std::to_string(::getpid()));
    fs::remove_all(a); fs::remove_all(b);

    GenOptions on;  on.tables_dir = a.string();  on.threads = 2;  on.prune = true;
    GenOptions off; off.tables_dir = b.string(); off.threads = 2; off.prune = false;
    generate(*Material::parse("KQvk"), on);
    generate(*Material::parse("KQvk"), off);

    auto bytes = [](const fs::path& p) {
        std::ifstream in(p, std::ios::binary);
        return std::vector<char>(std::istreambuf_iterator<char>(in), {});
    };
    CHECK(bytes(a / "KQvk.hm") == bytes(b / "KQvk.hm"));   // solvable: untouched
    // Kvk is unsolvable, so only the unpruned run writes a full table.
    auto pruned = TableReader::open((a / "Kvk.hm").string());
    auto full   = TableReader::open((b / "Kvk.hm").string());
    REQUIRE(pruned.has_value()); REQUIRE(full.has_value());
    CHECK(pruned->all_unsolvable());
    CHECK_FALSE(full->all_unsolvable());
    REQUIRE(pruned->plane_size() == full->plane_size());
    for (uint64_t c = 0; c < full->plane_size(); ++c)      // same values, both sides
        for (Color stm : {Color::White, Color::Black})
            REQUIRE(pruned->get(stm, c).dtm == full->get(stm, c).dtm);
    fs::remove_all(a); fs::remove_all(b);
}
```

- [ ] **Step 2: Run it**

`PATH="$HOME/.local/bin:$PATH" cmake --build build -j4` → FAILS: `'struct hm::GenOptions' has no member named 'prune'`.

- [ ] **Step 3: Implement**

In `src/generator/generator.h`, add to `GenOptions` after `force_ram`:

```cpp
    bool prune = true;       // skip slices that provably contain no helpmate
```

In `src/generator/generator.cpp`, inside `generate()`'s closure loop, immediately after the `if (std::filesystem::exists(path)) { ... continue; }` block and **before** the RAM re-check (so a doomed slice never costs RAM):

```cpp
        if (opt.prune) {
            // A slice has no solvable position iff it contains no mate and every
            // successor is itself entirely unsolvable (every solution ends in a
            // mate, in this slice or in one reachable by a capture/promotion).
            bool successors_dead = true;
            for (auto& s : m.successors()) {
                auto r = TableReader::open(opt.tables_dir + "/" + s.name() + ".hm");
                if (!r || !r->all_unsolvable()) { successors_dead = false; break; }
            }
            bool unsolvable = m.mating_side_is_bare_king() ||
                              (successors_dead && !slice_has_any_mate(m));
            if (unsolvable) {
                uint64_t ps = SliceIndex(m).size();
                nlohmann::json j;
                j["material"] = m.name();
                j["plane_size"] = ps;
                j["max_dtm"] = (int)DTM_UNSOLVABLE;
                j["all_unsolvable"] = true;
                j["cells"] = {{"invalid", nullptr}, {"unsolvable", ps}};
                j["generator_version"] = HELPMATE_VERSION;
                std::string meta = j.dump(2);
                std::filesystem::create_directories(opt.tables_dir);
                TableWriter::write_unsolvable(path, m, ps, meta);
                std::ofstream(opt.tables_dir + "/" + m.name() + ".stats.json",
                              std::ios::trunc) << meta;
                if (opt.verbose)
                    std::cerr << "pruned " << m.name()
                              << " (provably no helpmate; marker table written)\n";
                written.push_back(path);
                continue;
            }
        }
```

`HELPMATE_VERSION` is the same constant `stats_json()` stamps (`src/generator/generator.cpp:292`); it comes from `src/version.h`, which `generator.cpp` already includes — no new include needed. Task 7 bumps it to `"0.6.1"`.

Note on successors of a **bare-king** slice: they are bare-king too, so the structural test short-circuits before any table is opened — no ordering problem on a fresh directory.

- [ ] **Step 4: Run it**

```
PATH="$HOME/.local/bin:$PATH" cmake --build build -j4
taskset -c 0-3 ./build/helpmate_tests "generate prunes*"
taskset -c 0-3 ./build/helpmate_tests "generate leaves solvable*"
taskset -c 0-3 ./build/helpmate_tests            # whole fast suite
```
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/generator/generator.h src/generator/generator.cpp tests/cpp/test_generator_prune.cpp
git commit   # feat: prune provably unsolvable slices during generation
```

---

### Task 5: Oracle test — the three known unsolvable classes

**Files:**
- Test: `tests/cpp/test_generator_prune.cpp` (append)

**Interfaces:**
- Consumes: everything from Tasks 1-4.

- [ ] **Step 1: Write the failing test**

Append to `tests/cpp/test_generator_prune.cpp`. This pins the user-supplied classification against the derived rule; a disagreement is a real bug in one of them.

```cpp
TEST_CASE("derived prune rule reproduces the known unsolvable classes", "[slow]") {
    namespace fs = std::filesystem;
    fs::path dir = fs::temp_directory_path() /
                   ("hm_oracle_" + std::to_string(::getpid()));
    fs::remove_all(dir);
    GenOptions opt; opt.tables_dir = dir.string(); opt.threads = 4;

    // Generating these roots covers their whole closures, i.e. every material
    // named below.
    for (const char* root : {"KBvkqr", "KNvkq", "KNvkr", "KBvkb", "KNvkb"})
        generate(*Material::parse(root), opt);

    auto is_unsolvable = [&](const char* n) {
        auto r = TableReader::open((dir / (std::string(n) + ".hm")).string());
        REQUIRE(r.has_value());
        return r->max_dtm() == DTM_UNSOLVABLE;
    };

    // Kvk*: bare king. KBvk[qr]*: bishop vs queens/rooks. KNvk[q]*: knight vs queens.
    for (const char* n : {"Kvk", "Kvkq", "Kvkr", "Kvkqr",
                          "KBvk", "KBvkq", "KBvkr", "KBvkqr",
                          "KNvk", "KNvkq"}) {
        INFO("expected unsolvable: " << n);
        CHECK(is_unsolvable(n));
    }
    // Counter-oracle: neighbouring materials that DO have helpmates.
    for (const char* n : {"KNvkr", "KBvkb", "KNvkb"}) {
        INFO("expected solvable: " << n);
        CHECK_FALSE(is_unsolvable(n));
    }
    fs::remove_all(dir);
}
```

- [ ] **Step 2: Run it**

`PATH="$HOME/.local/bin:$PATH" cmake --build build -j4 && taskset -c 0-3 ./build/helpmate_tests "derived prune rule*"` → this is the first run; it may already pass. That is the point of an oracle test: it certifies Tasks 1-4 against an independent classification. If any `CHECK` fails, **stop and report it** — either the rule or the classification is wrong, and that is a finding, not something to paper over by editing the expectations.

- [ ] **Step 3: Confirm the tag**

The test is tagged `[slow]` so `make test` skips it (that lane runs `~[slow]`). Confirm it is excluded from the default run and included when asked:

```
taskset -c 0-3 ./build/helpmate_tests --list-tests | grep -c "derived prune rule"   # 1
taskset -c 0-3 ./build/helpmate_tests "~[slow]" | tail -2                            # suite green, this test not run
```

- [ ] **Step 4: Commit**

```bash
git add tests/cpp/test_generator_prune.cpp
git commit   # test: oracle for the known unsolvable material classes
```

---

### Task 6: `helpmate compact <dir>`

**Files:**
- Modify: `src/cli/main.cpp` (new subcommand + usage text), `CMakeLists.txt` (two `add_test` entries near the other `cli_*` tests)
- Test: `CMakeLists.txt` ctest cases (as below)

**Interfaces:**
- Consumes: `TableReader` (Task 2), `TableWriter::write_unsolvable` (Task 2).
- Produces: CLI `helpmate compact <DIR> [--dry-run]`. Exit codes follow the existing convention in `src/cli/main.cpp` (0 ok, 2 usage, 3 error) — read the file and match it.

- [ ] **Step 1: Write the failing test**

Add to `CMakeLists.txt` next to the existing `cli_*` tests (the `CLI_TT` directory already holds a generated `KQvk` + `Kvk` from `cli_gen`):

```cmake
add_test(NAME cli_compact_dry COMMAND helpmate compact ${CLI_TT} --dry-run)
add_test(NAME cli_compact COMMAND helpmate compact ${CLI_TT})
set_tests_properties(cli_compact_dry PROPERTIES PASS_REGULAR_EXPRESSION "would rewrite" DEPENDS cli_gen)
set_tests_properties(cli_compact PROPERTIES PASS_REGULAR_EXPRESSION "rewrote|already compact" DEPENDS cli_compact_dry)
```

- [ ] **Step 2: Run it**

`PATH="$HOME/.local/bin:$PATH" cmake --build build -j4 && cd build && taskset -c 0-3 ctest -R cli_compact --output-on-failure` → FAILS (unknown subcommand, exit 2).

- [ ] **Step 3: Implement**

In `src/cli/main.cpp`, add a `compact` branch alongside the existing subcommands. Behaviour:

```cpp
// helpmate compact <DIR> [--dry-run]
// Rewrites every .hm in DIR whose cells are all unsolvable as a marker table.
static int cmd_compact(const std::vector<std::string>& args) {
    if (args.empty()) { std::cerr << "error: compact needs a tables directory\n"; return 2; }
    std::string dir = args[0];
    bool dry = std::find(args.begin(), args.end(), "--dry-run") != args.end();
    if (!std::filesystem::is_directory(dir)) {
        std::cerr << "error: not a directory: " << dir << "\n"; return 2;
    }
    uint64_t reclaimed = 0; int rewritten = 0, skipped = 0;
    for (auto& e : std::filesystem::directory_iterator(dir)) {
        if (e.path().extension() != ".hm") continue;
        auto r = TableReader::open(e.path().string());
        if (!r) { std::cerr << "error: unreadable table " << e.path() << "\n"; return 3; }
        if (r->all_unsolvable()) { ++skipped; continue; }          // already compact
        bool any_solvable = false;
        for (uint64_t c = 0; c < r->plane_size() && !any_solvable; ++c)
            for (Color stm : {Color::White, Color::Black}) {
                uint8_t d = r->get(stm, c).dtm;
                if (d != DTM_UNSOLVABLE && d != DTM_INVALID) { any_solvable = true; break; }
            }
        if (any_solvable) { ++skipped; continue; }
        uint64_t size = std::filesystem::file_size(e.path());
        std::string name = r->material_name();
        std::string meta = r->meta_json();
        uint64_t ps = r->plane_size();
        std::cout << (dry ? "would rewrite " : "rewrote ") << name
                  << " (" << size / (1024 * 1024) << " MiB)\n";
        reclaimed += size;
        if (!dry) {
            auto mat = Material::parse(name);
            if (!mat) { std::cerr << "error: bad material in header: " << name << "\n"; return 3; }
            r.reset();                                   // unmap before replacing
            TableWriter::write_unsolvable(e.path().string(), *mat, ps, meta);
        }
        ++rewritten;
    }
    std::cout << (dry ? "would reclaim " : "reclaimed ") << reclaimed / (1024 * 1024)
              << " MiB from " << rewritten << " table(s); " << skipped
              << " left unchanged (solvable or already compact)\n";
    if (rewritten == 0) std::cout << "already compact\n";
    return 0;
}
```

Wire it into the dispatcher exactly like the neighbouring subcommands, and add a `compact` line to the usage text with the others. `DTM_UNSOLVABLE`/`DTM_INVALID` come from `src/chess/types.h:30`, already visible in `main.cpp` via `format/table_file.h`; `std::find` needs `<algorithm>` — add it to the includes if absent.

Task 7 also bumps `HELPMATE_VERSION` in `src/version.h` to `"0.6.1"`.

- [ ] **Step 4: Run it**

```
PATH="$HOME/.local/bin:$PATH" cmake --build build -j4
cd build && taskset -c 0-3 ctest -R "cli_" --output-on-failure && cd ..
taskset -c 0-3 ./build/helpmate_tests
```
Expected: every `cli_*` test passes (the new ones plus the existing ones), fast suite green.

- [ ] **Step 5: Verify by hand on a real pair of tables**

```bash
D=$(mktemp -d)
taskset -c 0-3 ./build/helpmate gen KQvk --tables $D          # KQvk solvable, Kvk not
ls -l $D/*.hm
taskset -c 0-3 ./build/helpmate compact $D --dry-run
taskset -c 0-3 ./build/helpmate compact $D
ls -l $D/*.hm                                                  # Kvk.hm now tiny, KQvk.hm unchanged
taskset -c 0-3 ./build/helpmate probe "8/7k/5K2/8/8/8/8/6Q1 b - - 0 1" --tables $D   # dtm=2 count=4
rm -rf $D
```
Paste the real output into the task report.

- [ ] **Step 6: Commit**

```bash
git add src/cli/main.cpp CMakeLists.txt
git commit   # feat: helpmate compact — rewrite all-unsolvable tables as markers
```

---

### Task 7: Push-hashing fix, docs, changelog, version bump

**Files:**
- Modify: `server/helpmate_server/tables_cli.py`, `docs/USAGE.md`, `README.md`, `CHANGELOG.md`, `pyproject.toml`, `server/helpmate_server/__init__.py`, `tests/server/test_packaging.py`
- Test: `tests/server/test_tables_cli.py` (existing suite must stay green)

**Interfaces:**
- Consumes: everything above.

- [ ] **Step 1: Fix the double hashing**

In `server/helpmate_server/tables_cli.py`'s push path, `build_manifest(tables, gen_version)` is currently called once inside `write_manifest` and again for the remote merge. Call `build_manifest` **once**, write that dict to the local `manifest.json` yourself (`json.dumps(..., indent=2, sort_keys=True)`, matching `write_manifest`'s formatting exactly), and use the same dict's `files` entries for the merge. Keep `manifest.write_manifest` in place for other callers.

- [ ] **Step 2: Verify no behaviour changed**

```
taskset -c 0-3 python -m pytest tests/server/test_tables_cli.py -v
```
Expected: all pass unchanged (the local manifest must remain byte-identical in content — the existing tests compare it).

- [ ] **Step 3: Version bump**

`pyproject.toml` → `version = "0.6.1"`; `server/helpmate_server/__init__.py` → `__version__ = "0.6.1"`; `tests/server/test_packaging.py` → expect `"0.6.1"`; `src/version.h:9` → `HELPMATE_VERSION = "0.6.1"` (this is what `helpmate --version` prints and what new `.stats.json` files record).

- [ ] **Step 4: Docs and changelog**

- `docs/USAGE.md`: document `helpmate compact <DIR> [--dry-run]` in the CLI section (real captured output from Task 6 Step 5), and add a short subsection explaining when a slice is pruned and what a marker table is.
- `README.md`: one line in the CLI overview mentioning `compact`.
- `CHANGELOG.md`: a `## [0.6.1] - <date>` section — prune of provably unsolvable slices, marker tables (format v2, readers accept v1 and v2), `helpmate compact`, single-hash push.

- [ ] **Step 5: Full verification**

```
PATH="$HOME/.local/bin:$PATH" cmake --build build -j4
taskset -c 0-3 ./build/helpmate_tests
cd build && taskset -c 0-3 ctest --output-on-failure && cd ..
taskset -c 0-3 python -m pytest tests/python tests/server -v
python3 tools/api_smoke.py --url http://127.0.0.1:8642   # only if a server is running; else skip
```
Expected: C++ fast suite green, ctest green, Python suites green.

- [ ] **Step 6: Commit**

```bash
git add server/helpmate_server/tables_cli.py pyproject.toml server/helpmate_server/__init__.py \
        tests/server/test_packaging.py docs/USAGE.md README.md CHANGELOG.md
git commit   # release: v0.6.1 — prune docs, single-hash push, version bump
```

---

## Verification checklist (whole plan)

- C++ fast suite and ctest green; Python suites green.
- `[slow]` oracle test passes when run explicitly.
- A pruned run and a `--no-prune` run agree cell-for-cell on `Kvk`; `KQvk.hm` is byte-identical between them.
- `helpmate compact` on a real directory shrinks the unsolvable table, leaves the solvable one untouched, and probing still works afterwards.
- Manual (coordinator, after merge): run `helpmate compact ~/tb --dry-run` and report the reclaimable total — do **not** rewrite the user's tables without asking, since a 6-piece generation may be writing there.
