# Theme Detection (v0.8) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Search the tablebase for positions whose optimal solutions show named composition themes — twelve themes, detected on the fly, available from the CLI, the HTTP API and the web dashboard.

**Architecture:** A new `src/core/themes/` module of *pure functions*: each detector takes a `Solution` (a structured optimal line: which unit moved, from/to, captures, promotions, and the board after each ply) and returns `bool`. `Tablebase::solutions()` produces those structures by the same walk `collect_lines()` already performs; `lines()` is untouched. A flat registry maps names to detectors, and CLI/API/dashboard each *enumerate the registry* rather than hard-coding names, so adding a theme later is one function plus one registry line. Themes are computed during a `mine` scan — no index, no file-format change.

**Tech Stack:** C++20 (Catch2 v3 tests, CMake), pybind11 bindings, FastAPI (pytest + httpx), vanilla ES modules (`node --test`, Playwright).

## Global Constraints

- **Max 4 cores for any build or test command.** Prefix every build/test invocation with `taskset -c 0-3`. Copied from `docs/ROADMAP.md`, "Standing constraints".
- **Never write to `~/tb`.** A multi-day 6-piece generation run is writing there. Reading is fine. Use `$(mktemp -d)` for scratch tables.
- **Never run bare `./build/helpmate_tests`** — that includes the `[slow]` lane (30–60 min). Always pass a filter: `"~[slow]"` or a tag like `"[themes]"`.
- **Never let CMake FetchContent clone from GitHub during pip installs.** Use `GIT_CONFIG_GLOBAL=/dev/null make install-dev`. Never delete `build/_deps`.
- **Never run a wildcard delete under `/tmp`** (e.g. `rm -rf /tmp/tmp.*`) — it is a shared directory.
- Commit trailer on every commit: `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`
- Spec: `docs/superpowers/specs/2026-08-03-theme-detection-design.md`. Where this plan and the spec disagree, the spec has been updated to match this plan.
- **Sentinel values** (`src/core/chess/types.h`): `DTM_MAX = 252`, `COUNT_SAT = 255`.
- **Registry order is the public order.** `helpmate themes`, `/v1/themes` and the dashboard multi-select all render `theme_registry()` in its declared order.

## File Structure

**Created:**
- `src/core/probe/solution.h` — `Ply`, `Solution`, `final_board()`. Lives under `probe/` because `Tablebase` produces it and `themes/` consumes it; this keeps `themes/` free of any dependency on `tablebase.h`.
- `src/core/themes/attack.h` / `attack.cpp` — square-attack primitives from a piece list.
- `src/core/themes/trajectory.h` / `trajectory.cpp` — per-unit square paths through a solution.
- `src/core/themes/mate_themes.h` / `mate_themes.cpp` — `pure`, `model`, `ideal`, `mirror`.
- `src/core/themes/line_themes.h` / `line_themes.cpp` — the eight ply-based detectors.
- `src/core/themes/registry.h` / `registry.cpp` — `Detector`, `ThemeDef`, `theme_registry()`, `find_theme()`, `detect()`.
- `src/core/tests/test_solutions.cpp`, `test_attack.cpp`, `test_mate_themes.cpp`, `test_line_themes.cpp`, `test_themes_registry.cpp`
- `src/packages/api/tests/test_api_themes.py`
- `src/packages/web/helpmate_web/static/js/lib/themes.js` + `src/packages/web/tests/js/themes.test.js`

**Modified:**
- `src/core/probe/tablebase.h` / `.cpp` — `solutions()`, `shape_of_solutions()`, `MineFilter::themes`, `mine()` integration.
- `src/core/CMakeLists.txt` — new sources and test files.
- `src/packages/cli/main.cpp` — `--theme`, `--themes`, `helpmate themes`.
- `src/packages/cli/CMakeLists.txt` — ctest cases.
- `src/packages/bindings/pymodule.cpp`, `src/packages/bindings/helpmate/__init__.py`
- `src/packages/api/helpmate_server/app.py`
- `src/packages/web/helpmate_web/static/js/{api.js,mine.js,explorer.js}`, `static/index.html`, `static/css/app.css`
- `docs/USAGE.md`, `docs/ROADMAP.md`, `README.md`, `VERSION`

---

### Task 1: Structured solutions

**Files:**
- Create: `src/core/probe/solution.h`
- Modify: `src/core/probe/tablebase.h`, `src/core/probe/tablebase.cpp`
- Modify: `src/core/CMakeLists.txt`
- Test: `src/core/tests/test_solutions.cpp`

**Interfaces:**
- Consumes: `Board` (`src/core/chess/board.h`), `Move`, `Piece`, `PieceType`, `Color` (`src/core/chess/types.h`), `Tablebase::value_of` (private, existing).
- Produces: `hm::Ply`, `hm::Solution`, `hm::final_board(const Solution&)`, `Tablebase::solutions(fen, max=100) -> std::vector<Solution>`. Every later task depends on these exact names.

- [ ] **Step 1: Write the failing test**

Create `src/core/tests/test_solutions.cpp`:

```cpp
#include "probe/tablebase.h"
#include "probe/solution.h"
#include "generator/generator.h"
#include <catch2/catch_test_macros.hpp>
#include <filesystem>
#include <set>

using namespace hm;

// The golden KQvk position: dtm 2, count 4, four known optimal solutions.
// Already pinned by tests across the C++, Python and CLI suites.
static const char* kGolden = "8/7k/5K2/8/8/8/8/6Q1 b - - 0 1";

namespace {
std::string gen_kqvk() {
    static std::string dir;
    if (dir.empty()) {
        dir = (std::filesystem::temp_directory_path() / "hm_solutions_test").string();
        std::filesystem::create_directories(dir);
        generate_material(*Material::parse("KQvk"), dir, GenerateOptions{});
    }
    return dir;
}
}  // namespace

TEST_CASE("solutions() mirrors lines() one-for-one", "[themes][solutions]") {
    Tablebase tb(gen_kqvk());
    auto ls = tb.lines(kGolden, 100);
    auto ss = tb.solutions(kGolden, 100);
    REQUIRE(ss.size() == ls.size());
    REQUIRE(ss.size() == 4);
    for (size_t i = 0; i < ss.size(); ++i) REQUIRE(ss[i].plies.size() == ls[i].size());
}

TEST_CASE("every solution carries the queried position as start", "[themes][solutions]") {
    Tablebase tb(gen_kqvk());
    for (const auto& s : tb.solutions(kGolden, 100)) REQUIRE(s.start.fen() == kGolden);
}

TEST_CASE("the last ply of every optimal solution is mate", "[themes][solutions]") {
    Tablebase tb(gen_kqvk());
    for (const auto& s : tb.solutions(kGolden, 100)) {
        REQUIRE(!s.plies.empty());
        REQUIRE(s.plies.back().is_check);
        REQUIRE(final_board(s).state() == PosState::Checkmate);
    }
}

TEST_CASE("plies record the moving unit and its from/to", "[themes][solutions]") {
    Tablebase tb(gen_kqvk());
    auto ss = tb.solutions(kGolden, 100);
    for (const auto& s : ss) {
        // h#1: Black moves first, then White mates.
        REQUIRE(s.plies.size() == 2);
        REQUIRE(s.plies[0].piece.color == Color::Black);
        REQUIRE(s.plies[0].piece.type == PieceType::King);
        REQUIRE(s.plies[1].piece.color == Color::White);
        for (const auto& p : s.plies) {
            REQUIRE(p.from != p.to);
            REQUIRE_FALSE(p.captured.has_value());   // no captures in this material
            REQUIRE_FALSE(p.promotion.has_value());
            REQUIRE_FALSE(p.is_ep);
        }
    }
}

TEST_CASE("a position that is already mate yields one empty solution", "[themes][solutions]") {
    Tablebase tb(gen_kqvk());
    const char* mated = "8/8/8/8/8/8/8/kQK5 b - - 0 1";   // dtm 0
    auto ss = tb.solutions(mated, 100);
    REQUIRE(ss.size() == 1);
    REQUIRE(ss[0].plies.empty());
    REQUIRE(final_board(ss[0]).fen() == mated);           // start is the mate
}

TEST_CASE("solutions() rejects a bad FEN the same way lines() does",
          "[themes][solutions]") {
    Tablebase tb(gen_kqvk());
    REQUIRE_THROWS_AS(tb.solutions("garbage", 10), std::invalid_argument);
}
```

- [ ] **Step 2: Run test to verify it fails**

First register the new test file. In `src/core/CMakeLists.txt`, add `tests/test_solutions.cpp` to the `add_executable(helpmate_tests ...)` source list (append after `tests/test_block_codec.cpp`).

Run: `taskset -c 0-3 cmake --build build -j4 2>&1 | tail -20`
Expected: FAIL — `fatal error: probe/solution.h: No such file or directory`

- [ ] **Step 3: Create the solution type**

Create `src/core/probe/solution.h`:

```cpp
#pragma once
#include "chess/board.h"
#include "chess/types.h"
#include <optional>
#include <vector>

namespace hm {

// One ply of an optimal solution, carrying everything a theme detector needs.
// SAN is deliberately absent: `Tablebase::lines()` stays the cheaper path for
// callers that only want text, and nothing here needs a move rendered.
struct Ply {
    Piece piece;                        // what moved; `type` is the type BEFORE any promotion
    uint8_t from = 0, to = 0;
    std::optional<PieceType> captured;  // nullopt if the ply is quiet
    std::optional<PieceType> promotion; // nullopt if the ply is not a promotion
    bool is_ep = false;
    bool is_check = false;              // the side to move AFTER this ply is in check
    Board after;                        // the position after this ply
};

// One optimal solution from a queried position.
//
// `start` is not redundant with `plies`. A position with dtm == 0 is already
// mate and carries no plies at all, and the mate-position detectors still need
// a board to read. `self-block` also needs the position immediately before a
// blocking move, which for the first ply is `start`.
struct Solution {
    Board start;
    std::vector<Ply> plies;
};

// The mating position: the board after the last ply, or `start` when the
// queried position was itself the mate.
inline const Board& final_board(const Solution& s) {
    return s.plies.empty() ? s.start : s.plies.back().after;
}

}  // namespace hm
```

- [ ] **Step 4: Declare `solutions()` on Tablebase**

In `src/core/probe/tablebase.h`, add `#include "probe/solution.h"` beside the existing includes. Then, in the public section immediately after the `lines()` declaration, add:

```cpp
    // All optimal solutions in structured form, capped at `max`. Same walk and
    // same cap as lines(), but keeping the mover, from/to, captures,
    // promotions and the board after each ply -- everything SAN throws away.
    std::vector<Solution> solutions(const std::string& fen, int max = 100) const;
```

And in the private section, beside `collect_lines`:

```cpp
    void collect_solutions(Board& b, std::vector<Ply>& path, std::vector<Solution>& out,
                           const Board& start, int max) const;
```

- [ ] **Step 5: Implement the walk**

In `src/core/probe/tablebase.cpp`, immediately after `Tablebase::lines()`, add:

```cpp
void Tablebase::collect_solutions(Board& b, std::vector<Ply>& path, std::vector<Solution>& out,
                                   const Board& start, int max) const {
    if ((int)out.size() >= max) return;
    ValuePair v = value_of(b);
    if (v.dtm == 0) { out.push_back(Solution{start, path}); return; }
    for (const Move& m : b.legal_moves()) {
        if ((int)out.size() >= max) return;
        b.make(m);
        ValuePair nv = value_of(b);
        bool on_optimal = nv.dtm <= DTM_MAX && (int)nv.dtm == (int)v.dtm - 1;
        b.unmake(m);
        if (!on_optimal) continue;

        Ply p;
        p.from = m.from;
        p.to = m.to;
        p.promotion = m.promotion();
        p.is_ep = m.is_ep();
        for (const auto& pp : b.pieces()) {           // b is still PRE-move here
            if (pp.square == m.from) p.piece = pp.piece;
            else if (pp.square == m.to) p.captured = pp.piece.type;
        }
        // An en-passant capture takes a pawn that is NOT on m.to, so the scan
        // above cannot see it.
        if (p.is_ep) p.captured = PieceType::Pawn;

        b.make(m);
        p.is_check = b.in_check();
        p.after = b;
        path.push_back(std::move(p));
        collect_solutions(b, path, out, start, max);
        path.pop_back();
        b.unmake(m);
    }
}

std::vector<Solution> Tablebase::solutions(const std::string& fen, int max) const {
    auto b = Board::from_fen(fen);
    if (!b) throw std::invalid_argument("bad FEN (or castling rights): " + fen);
    Board start = *b;
    std::vector<Solution> out;
    std::vector<Ply> path;
    collect_solutions(*b, path, out, start, max);
    return out;
}
```

- [ ] **Step 6: Run the tests**

Run: `taskset -c 0-3 cmake --build build -j4 && taskset -c 0-3 ./build/helpmate_tests "[solutions]"`
Expected: PASS, 6 test cases.

- [ ] **Step 7: Confirm `lines()` did not change**

Run: `taskset -c 0-3 ./build/helpmate_tests "[probe]"`
Expected: PASS — `solutions()` is additive; any failure here means `collect_lines` was disturbed.

- [ ] **Step 8: Commit**

```bash
git add src/core/probe/solution.h src/core/probe/tablebase.h src/core/probe/tablebase.cpp \
        src/core/CMakeLists.txt src/core/tests/test_solutions.cpp
git commit -m "feat(core): structured optimal solutions beside lines()

SAN text discards the mover, from/to, captures and the board after each ply --
everything a theme detector needs. solutions() rebuilds the same walk keeping
all of it; lines() is untouched, so nothing downstream changes and the SAN path
stays the cheaper option.

Solution carries the start board because a dtm-0 position is already mate and
has no plies at all -- without it a mate-position detector would have nothing
to read.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Attack primitives

**Files:**
- Create: `src/core/themes/attack.h`, `src/core/themes/attack.cpp`
- Modify: `src/core/CMakeLists.txt`
- Test: `src/core/tests/test_attack.cpp`

**Interfaces:**
- Consumes: `PlacedPiece`, `Piece`, `PieceType`, `Color`, `sq_file`, `sq_rank` from `chess/types.h`.
- Produces: `hm::themes::attackers_of(pieces, by, sq, ignore_king_of = nullopt) -> int`, `hm::themes::piece_attacks(pieces, p, sq, ignore_king_of = nullopt) -> bool`, `hm::themes::king_field(sq) -> std::vector<int>`. Task 3 and Task 4 both depend on these.

- [ ] **Step 1: Write the failing test**

Create `src/core/tests/test_attack.cpp`:

```cpp
#include "themes/attack.h"
#include "chess/board.h"
#include <catch2/catch_test_macros.hpp>

using namespace hm;
using namespace hm::themes;

static std::vector<PlacedPiece> from_fen(const std::string& fen) {
    auto b = Board::from_fen(fen);
    REQUIRE(b);
    return b->pieces();
}

static int sq(const char* name) { return (name[1] - '1') * 8 + (name[0] - 'a'); }

TEST_CASE("king_field is the on-board neighbourhood", "[themes][attack]") {
    REQUIRE(king_field(sq("e4")).size() == 8);
    REQUIRE(king_field(sq("a1")).size() == 3);
    REQUIRE(king_field(sq("h8")).size() == 3);
    REQUIRE(king_field(sq("a4")).size() == 5);
}

TEST_CASE("sliders are blocked by intervening units", "[themes][attack]") {
    // White rook a1, white pawn a3: a3 blocks the file, so a5 is unattacked.
    auto ps = from_fen("8/8/8/8/8/P7/8/R3K2k w - - 0 1");
    REQUIRE(attackers_of(ps, Color::White, sq("a2")) == 1);
    REQUIRE(attackers_of(ps, Color::White, sq("a5")) == 0);
}

TEST_CASE("pawns attack diagonally, never forward", "[themes][attack]") {
    auto ps = from_fen("8/8/8/8/8/8/4P3/4K2k w - - 0 1");
    REQUIRE(attackers_of(ps, Color::White, sq("d3")) == 1);
    REQUIRE(attackers_of(ps, Color::White, sq("f3")) == 1);
    REQUIRE(attackers_of(ps, Color::White, sq("e3")) == 0);   // the push square
    REQUIRE(attackers_of(ps, Color::White, sq("e4")) == 0);
}

TEST_CASE("black pawns attack down the board", "[themes][attack]") {
    auto ps = from_fen("4k3/4p3/8/8/8/8/8/4K3 b - - 0 1");
    REQUIRE(attackers_of(ps, Color::Black, sq("d6")) == 1);
    REQUIRE(attackers_of(ps, Color::Black, sq("f6")) == 1);
    REQUIRE(attackers_of(ps, Color::Black, sq("e6")) == 0);
}

TEST_CASE("attackers are counted, not merely detected", "[themes][attack]") {
    // Rook a8 and rook h8 both bear on e8.
    auto ps = from_fen("R6R/8/8/8/8/8/8/4K2k w - - 0 1");
    REQUIRE(attackers_of(ps, Color::White, sq("e8")) == 2);
}

TEST_CASE("a pinned unit still counts as attacking", "[themes][attack]") {
    // White bishop c3 is pinned to Ke1 by the black rook on e-file... it still
    // controls its diagonal for the purpose of the black king's legality.
    auto ps = from_fen("8/8/8/8/8/2B5/8/4K2k w - - 0 1");
    REQUIRE(attackers_of(ps, Color::White, sq("e5")) == 1);
}

TEST_CASE("ignore_king_of unmasks the square behind the mated king",
          "[themes][attack]") {
    // White rook h1 checks the black king on h5. h6 is NOT a flight square --
    // the king cannot run along the checking line -- but with the king on the
    // board it blocks the ray and a naive scan reports h6 unattacked.
    auto ps = from_fen("8/8/8/7k/8/8/8/K6R b - - 0 1");
    REQUIRE(attackers_of(ps, Color::White, sq("h6")) == 0);
    REQUIRE(attackers_of(ps, Color::White, sq("h6"), Color::Black) == 1);
    // The king's own square is unaffected by removing the king.
    REQUIRE(attackers_of(ps, Color::White, sq("h5")) == 1);
}

TEST_CASE("piece_attacks isolates a single unit", "[themes][attack]") {
    auto ps = from_fen("R6R/8/8/8/8/8/8/4K2k w - - 0 1");
    PlacedPiece ra{{Color::White, PieceType::Rook}, (uint8_t)sq("a8")};
    PlacedPiece rh{{Color::White, PieceType::Rook}, (uint8_t)sq("h8")};
    REQUIRE(piece_attacks(ps, ra, sq("e8")));
    REQUIRE(piece_attacks(ps, rh, sq("e8")));
    REQUIRE_FALSE(piece_attacks(ps, ra, sq("e5")));
    REQUIRE_FALSE(piece_attacks(ps, ra, sq("a8")));   // never attacks its own square
}

TEST_CASE("knights jump over occupied squares", "[themes][attack]") {
    auto ps = from_fen("8/8/8/8/8/PPP5/PNP5/K1P4k w - - 0 1");
    REQUIRE(attackers_of(ps, Color::White, sq("d3")) == 1);   // the knight, boxed in
}
```

- [ ] **Step 2: Run test to verify it fails**

Add `themes/attack.cpp` to `HELPMATE_SOURCES` and `tests/test_attack.cpp` to the `helpmate_tests` source list in `src/core/CMakeLists.txt`.

Run: `taskset -c 0-3 cmake --build build -j4 2>&1 | tail -20`
Expected: FAIL — `Cannot find source file: themes/attack.cpp`

- [ ] **Step 3: Write the header**

Create `src/core/themes/attack.h`:

```cpp
#pragma once
#include "chess/types.h"
#include <optional>
#include <vector>

namespace hm::themes {

// How many units of colour `by` attack `sq`.
//
// A PINNED unit counts as attacking. It still controls the square for the
// purpose of the enemy king's legality, and "would this pin actually matter"
// is not decidable from the position alone.
//
// `ignore_king_of`, when set, removes that colour's king from the occupancy
// before tracing sliders. Every FIELD-SQUARE test needs this: a rook on h1
// checking a king on h5 also denies h6, but with the king on the board it
// blocks the ray and h6 reads as unattacked. Tests of the king's OWN square
// use the full board.
int attackers_of(const std::vector<PlacedPiece>& pieces, Color by, int sq,
                 std::optional<Color> ignore_king_of = std::nullopt);

// Does this one unit attack `sq`, given `pieces` as the occupancy? Same
// pinned-counts and ignore_king_of rules as attackers_of. Used to ask whether
// a particular unit participates in a mate.
bool piece_attacks(const std::vector<PlacedPiece>& pieces, const PlacedPiece& p, int sq,
                   std::optional<Color> ignore_king_of = std::nullopt);

// The on-board squares adjacent to `sq` -- 8 in the middle, 3 in a corner.
std::vector<int> king_field(int sq);

}  // namespace hm::themes
```

- [ ] **Step 4: Write the implementation**

Create `src/core/themes/attack.cpp`:

```cpp
#include "themes/attack.h"
#include <array>
#include <cstdlib>
#include <utility>

namespace hm::themes {
namespace {

constexpr std::array<std::pair<int, int>, 8> kKingDirs{
    {{1, 0}, {-1, 0}, {0, 1}, {0, -1}, {1, 1}, {1, -1}, {-1, 1}, {-1, -1}}};
constexpr std::array<std::pair<int, int>, 8> kKnightDirs{
    {{1, 2}, {2, 1}, {2, -1}, {1, -2}, {-1, -2}, {-2, -1}, {-2, 1}, {-1, 2}}};

inline bool on_board(int f, int r) { return f >= 0 && f < 8 && r >= 0 && r < 8; }
inline int sq_of(int f, int r) { return r * 8 + f; }

// True when this unit is invisible for the current query.
inline bool hidden(const PlacedPiece& p, std::optional<Color> ignore_king_of) {
    return ignore_king_of && p.piece.type == PieceType::King && p.piece.color == *ignore_king_of;
}

}  // namespace

std::vector<int> king_field(int sq) {
    std::vector<int> out;
    int f = sq_file(sq), r = sq_rank(sq);
    for (auto [df, dr] : kKingDirs)
        if (on_board(f + df, r + dr)) out.push_back(sq_of(f + df, r + dr));
    return out;
}

int attackers_of(const std::vector<PlacedPiece>& pieces, Color by, int sq,
                 std::optional<Color> ignore_king_of) {
    std::array<int, 64> occ;
    occ.fill(-1);
    for (size_t i = 0; i < pieces.size(); ++i)
        if (!hidden(pieces[i], ignore_king_of)) occ[pieces[i].square] = (int)i;

    int n = 0;
    const int f = sq_file(sq), r = sq_rank(sq);

    auto steps = [&](const auto& dirs, PieceType want) {
        for (auto [df, dr] : dirs) {
            if (!on_board(f + df, r + dr)) continue;
            int i = occ[sq_of(f + df, r + dr)];
            if (i >= 0 && pieces[i].piece.color == by && pieces[i].piece.type == want) ++n;
        }
    };
    steps(kKnightDirs, PieceType::Knight);
    steps(kKingDirs, PieceType::King);

    // A pawn of colour `by` attacks `sq` from one rank BEHIND it in that
    // colour's direction of travel -- diagonally only, never the push square.
    const int pr = r - (by == Color::White ? 1 : -1);
    for (int df : {-1, 1}) {
        if (!on_board(f + df, pr)) continue;
        int i = occ[sq_of(f + df, pr)];
        if (i >= 0 && pieces[i].piece.color == by && pieces[i].piece.type == PieceType::Pawn) ++n;
    }

    // Sliders: walk each ray outward and stop at the first occupied square.
    for (auto [df, dr] : kKingDirs) {
        const bool diagonal = (df != 0 && dr != 0);
        for (int step = 1;; ++step) {
            int nf = f + df * step, nr = r + dr * step;
            if (!on_board(nf, nr)) break;
            int i = occ[sq_of(nf, nr)];
            if (i < 0) continue;
            const Piece& pc = pieces[i].piece;
            if (pc.color == by &&
                (pc.type == PieceType::Queen ||
                 pc.type == (diagonal ? PieceType::Bishop : PieceType::Rook)))
                ++n;
            break;  // the ray is blocked either way
        }
    }
    return n;
}

bool piece_attacks(const std::vector<PlacedPiece>& pieces, const PlacedPiece& p, int sq,
                   std::optional<Color> ignore_king_of) {
    if ((int)p.square == sq) return false;
    const int pf = sq_file(p.square), pr = sq_rank(p.square);
    const int tf = sq_file(sq), tr = sq_rank(sq);
    const int df = tf - pf, dr = tr - pr;

    switch (p.piece.type) {
        case PieceType::Knight:
            return (std::abs(df) == 1 && std::abs(dr) == 2) ||
                   (std::abs(df) == 2 && std::abs(dr) == 1);
        case PieceType::King:
            return std::abs(df) <= 1 && std::abs(dr) <= 1;
        case PieceType::Pawn:
            return std::abs(df) == 1 && dr == (p.piece.color == Color::White ? 1 : -1);
        default:
            break;
    }
    const bool diagonal = (std::abs(df) == std::abs(dr));
    const bool straight = (df == 0 || dr == 0);
    if (p.piece.type == PieceType::Bishop && !diagonal) return false;
    if (p.piece.type == PieceType::Rook && !straight) return false;
    if (p.piece.type == PieceType::Queen && !diagonal && !straight) return false;

    const int sf = (df > 0) - (df < 0), sr = (dr > 0) - (dr < 0);
    for (int f = pf + sf, r = pr + sr; f != tf || r != tr; f += sf, r += sr) {
        const int between = sq_of(f, r);
        for (const auto& o : pieces)
            if (!hidden(o, ignore_king_of) && (int)o.square == between) return false;
    }
    return true;
}

}  // namespace hm::themes
```

- [ ] **Step 5: Run the tests**

Run: `taskset -c 0-3 cmake --build build -j4 && taskset -c 0-3 ./build/helpmate_tests "[attack]"`
Expected: PASS, 9 test cases.

- [ ] **Step 6: Prove the ignore_king_of test is not vacuous**

Temporarily delete the `if (!hidden(pieces[i], ignore_king_of))` guard in `attackers_of` (make it unconditional), rebuild, and run `taskset -c 0-3 ./build/helpmate_tests "[attack]"`.
Expected: the "ignore_king_of unmasks the square behind the mated king" case FAILS. Restore the guard and confirm it passes again. If it passed with the guard removed, the test is not testing what it claims — fix the test before continuing.

- [ ] **Step 7: Commit**

```bash
git add src/core/themes/attack.h src/core/themes/attack.cpp \
        src/core/tests/test_attack.cpp src/core/CMakeLists.txt
git commit -m "feat(themes): square-attack primitives

Pinned units count as attacking -- they still control squares for the enemy
king's legality, and 'would this pin actually matter' is not decidable from
the position.

ignore_king_of exists for one specific correctness rule: a rook checking along
a file also denies the square directly behind the king, but with the king on
the board it blocks the ray and the square reads as unattacked. Every
field-square test removes the mated king first.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Mate-position detectors

**Files:**
- Create: `src/core/themes/mate_themes.h`, `src/core/themes/mate_themes.cpp`
- Modify: `src/core/CMakeLists.txt`
- Test: `src/core/tests/test_mate_themes.cpp`

**Interfaces:**
- Consumes: `hm::Solution`, `hm::final_board` (Task 1); `attackers_of`, `piece_attacks`, `king_field` (Task 2).
- Produces: `hm::themes::is_pure(const Solution&)`, `is_model(...)`, `is_ideal(...)`, `is_mirror(...)` — all `bool(const Solution&)`, matching the `Detector` signature Task 5 requires.

- [ ] **Step 1: Write the failing test**

Create `src/core/tests/test_mate_themes.cpp`:

```cpp
#include "themes/mate_themes.h"
#include "probe/solution.h"
#include <catch2/catch_test_macros.hpp>

using namespace hm;
using namespace hm::themes;

// A mate-position detector reads only the final board, so a Solution with a
// start position and no plies is a complete input. No table file needed.
static Solution at(const std::string& fen) {
    auto b = Board::from_fen(fen);
    REQUIRE(b);
    return Solution{*b, {}};
}

TEST_CASE("a corner mate by rook and king is pure", "[themes][mate]") {
    // Kh8 mated: Ra8 gives check along the 8th; Kf7 covers g7 and g8; h7 is
    // covered by nothing but the rook... check each field square is guarded
    // exactly once.
    auto s = at("R5k1/5K2/8/8/8/8/8/8 b - - 0 1");
    REQUIRE(final_board(s).state() == PosState::Checkmate);
    REQUIRE(is_pure(s));
}

TEST_CASE("double check is impure", "[themes][mate]") {
    // Two white units bear on the king's square at once, so the king's square
    // is attacked twice and the mate is not pure under our definition.
    auto s = at("R5k1/5K2/6N1/8/8/8/8/8 b - - 0 1");
    if (final_board(s).state() == PosState::Checkmate)
        REQUIRE(is_pure(s) == (attackersOfKingIsOne(s)));
    // Guard: this fixture exists to pin the rule, so assert the rule directly.
    REQUIRE_FALSE(is_pure(at("6k1/5K2/8/8/8/8/8/R5R1 b - - 0 1")));
}

TEST_CASE("an over-guarded flight square is impure", "[themes][mate]") {
    // Near-miss: the same mate with a second white unit redundantly covering
    // one flight square. Purity fails even though the mate is unchanged.
    auto pure_one = at("R5k1/5K2/8/8/8/8/8/8 b - - 0 1");
    auto doubled  = at("R5k1/5K2/8/8/8/8/8/6R1 b - - 0 1");
    REQUIRE(is_pure(pure_one));
    REQUIRE_FALSE(is_pure(doubled));
}

TEST_CASE("a black unit on an attacked field square is double duty",
          "[themes][mate]") {
    // The black rook blocks g8 AND g8 is attacked by White: the square is
    // unavailable for two reasons at once, which breaks purity.
    auto s = at("R4rk1/5K2/8/8/6R1/8/8/8 b - - 0 1");
    REQUIRE_FALSE(is_pure(s));
}

TEST_CASE("mirror mate: the whole king field is empty", "[themes][mate]") {
    REQUIRE(is_mirror(at("R5k1/5K2/8/8/8/8/8/8 b - - 0 1")));
    // Near-miss: one black unit standing beside the king.
    REQUIRE_FALSE(is_mirror(at("R4rk1/5K2/8/8/8/8/8/8 b - - 0 1")));
}

TEST_CASE("model mate: every white officer participates", "[themes][mate]") {
    auto s = at("R5k1/5K2/8/8/8/8/8/8 b - - 0 1");
    REQUIRE(is_model(s));
    // Near-miss: add an idle white bishop far from the action. Still a pure
    // mate, no longer a model mate.
    auto idle = at("R5k1/5K2/8/8/8/8/8/B7 b - - 0 1");
    REQUIRE(is_pure(idle));
    REQUIRE_FALSE(is_model(idle));
}

TEST_CASE("model exempts the white king and white pawns", "[themes][mate]") {
    // A white pawn that does nothing must not break model-ness.
    auto s = at("R5k1/5K2/8/8/8/8/P7/8 b - - 0 1");
    REQUIRE(is_pure(s));
    REQUIRE(is_model(s));
    REQUIRE_FALSE(is_ideal(s));   // ideal exempts nothing
}

TEST_CASE("ideal mate: no exemptions at all", "[themes][mate]") {
    auto s = at("R5k1/5K2/8/8/8/8/8/8 b - - 0 1");
    REQUIRE(is_model(s));
    REQUIRE(is_ideal(s));         // Ra8 checks, Kf7 covers g7/g8, nothing idle
}

TEST_CASE("a black unit off the king field breaks ideal", "[themes][mate]") {
    // The black rook is not adjacent to its king, so it does not participate.
    auto s = at("R5k1/5K2/8/8/8/8/8/1r6 b - - 0 1");
    REQUIRE_FALSE(is_ideal(s));
}

TEST_CASE("ideal implies model implies pure", "[themes][mate]") {
    for (const char* fen : {"R5k1/5K2/8/8/8/8/8/8 b - - 0 1",
                            "R5k1/5K2/8/8/8/8/P7/8 b - - 0 1",
                            "R4rk1/5K2/8/8/6R1/8/8/8 b - - 0 1",
                            "6k1/5K2/8/8/8/8/8/R5R1 b - - 0 1"}) {
        auto s = at(fen);
        if (is_ideal(s)) REQUIRE(is_model(s));
        if (is_model(s)) REQUIRE(is_pure(s));
    }
}

TEST_CASE("a position with no black king detects nothing", "[themes][mate]") {
    auto s = at("8/8/8/8/8/8/8/R3K3 w - - 0 1");
    REQUIRE_FALSE(is_pure(s));
    REQUIRE_FALSE(is_model(s));
    REQUIRE_FALSE(is_ideal(s));
    REQUIRE_FALSE(is_mirror(s));
}
```

**Note for the implementer:** the "double check is impure" case above contains a call to a helper `attackersOfKingIsOne` that does not exist — it is a deliberate placeholder marking a fixture you must verify. **Delete those first three lines of that test case** and keep only the final `REQUIRE_FALSE(...)` assertion, after confirming with `Board::from_fen(...)->state() == PosState::Checkmate` that the FEN really is mate. If any FEN in this file is not actually checkmate, fix the FEN — a detector asserted against a non-mate proves nothing.

- [ ] **Step 2: Verify every fixture FEN really is mate**

Before implementing, write a scratch check. Run:

```bash
cat > /tmp/claude-1000/-home-os-development-8pieces-helpmate/1276e24f-dd94-4959-9c52-73b31854300e/scratchpad/checkmate.py <<'EOF'
import chess
FENS = ["R5k1/5K2/8/8/8/8/8/8 b - - 0 1",
        "6k1/5K2/8/8/8/8/8/R5R1 b - - 0 1",
        "R5k1/5K2/8/8/8/8/8/6R1 b - - 0 1",
        "R4rk1/5K2/8/8/6R1/8/8/8 b - - 0 1",
        "R4rk1/5K2/8/8/8/8/8/8 b - - 0 1",
        "R5k1/5K2/8/8/8/8/8/B7 b - - 0 1",
        "R5k1/5K2/8/8/8/8/P7/8 b - - 0 1",
        "R5k1/5K2/8/8/8/8/8/1r6 b - - 0 1"]
for f in FENS:
    b = chess.Board(f)
    print(f"{'MATE ' if b.is_checkmate() else 'NOT  '} {f}")
EOF
taskset -c 0-3 python3 /tmp/claude-1000/-home-os-development-8pieces-helpmate/1276e24f-dd94-4959-9c52-73b31854300e/scratchpad/checkmate.py
```

If `python-chess` is not installed, install it into a scratch venv (`GIT_CONFIG_GLOBAL=/dev/null python3 -m pip install --user python-chess`) or verify with `Board::from_fen(fen)->state()` in a throwaway Catch2 case instead. **Every FEN used as a positive or near-miss mate fixture must print MATE.** Replace any that does not, and update the test file to match.

- [ ] **Step 3: Run test to verify it fails**

Add `themes/mate_themes.cpp` to `HELPMATE_SOURCES` and `tests/test_mate_themes.cpp` to `helpmate_tests` in `src/core/CMakeLists.txt`.

Run: `taskset -c 0-3 cmake --build build -j4 2>&1 | tail -20`
Expected: FAIL — `themes/mate_themes.h: No such file or directory`

- [ ] **Step 4: Write the header**

Create `src/core/themes/mate_themes.h`:

```cpp
#pragma once
#include "probe/solution.h"

namespace hm::themes {

// Detectors that read only the mating position -- the board after the last
// ply, or the queried board itself when it was already mate. All four share
// the Detector signature so the registry stays uniform.

// Every square of the black king's field is unavailable for EXACTLY ONE
// reason, and the king's own square is attacked exactly once. A square both
// occupied by a black unit and attacked by White is doing double duty and
// breaks purity; so does double check.
bool is_pure(const Solution& s);

// pure, and every white unit except the king and pawns participates --
// attacks the king's square or a field square, or stands on a field square.
bool is_model(const Solution& s);

// model, with no exemptions: the white king and white pawns must participate
// too, and every black unit other than the king must stand on a field square.
bool is_ideal(const Solution& s);

// Every square adjacent to the black king is empty, of either colour.
bool is_mirror(const Solution& s);

}  // namespace hm::themes
```

- [ ] **Step 5: Write the implementation**

Create `src/core/themes/mate_themes.cpp`:

```cpp
#include "themes/mate_themes.h"
#include "themes/attack.h"

namespace hm::themes {
namespace {

struct MateInfo {
    bool valid = false;              // false when there is no black king on the board
    int bk = -1;
    std::vector<PlacedPiece> pieces;
    std::vector<int> field;
};

MateInfo mate_info(const Solution& s) {
    MateInfo mi;
    mi.pieces = final_board(s).pieces();
    for (const auto& p : mi.pieces)
        if (p.piece.type == PieceType::King && p.piece.color == Color::Black) mi.bk = p.square;
    if (mi.bk < 0) return mi;
    mi.field = king_field(mi.bk);
    mi.valid = true;
    return mi;
}

const PlacedPiece* at_square(const std::vector<PlacedPiece>& ps, int sq) {
    for (const auto& p : ps)
        if ((int)p.square == sq) return &p;
    return nullptr;
}

bool on_field(const MateInfo& mi, int sq) {
    for (int f : mi.field)
        if (f == sq) return true;
    return false;
}

// A unit participates in the mate if it bears on the king's square or on any
// square of the king's field, or if it blocks a field square by standing on it.
bool participates(const MateInfo& mi, const PlacedPiece& p) {
    if (piece_attacks(mi.pieces, p, mi.bk)) return true;
    if (on_field(mi, p.square)) return true;
    for (int f : mi.field)
        if (piece_attacks(mi.pieces, p, f, Color::Black)) return true;
    return false;
}

}  // namespace

bool is_pure(const Solution& s) {
    MateInfo mi = mate_info(s);
    if (!mi.valid) return false;
    // The king's own square is judged on the FULL board: exactly one checker,
    // so double check is impure.
    if (attackers_of(mi.pieces, Color::White, mi.bk) != 1) return false;
    for (int f : mi.field) {
        // Field squares are judged with the mated king REMOVED, so a checking
        // slider also denies the square directly behind the king.
        const int a = attackers_of(mi.pieces, Color::White, f, Color::Black);
        const PlacedPiece* occ = at_square(mi.pieces, f);
        if (!occ) {
            if (a != 1) return false;                       // unguarded, or guarded twice
        } else if (occ->piece.color == Color::Black) {
            if (a != 0) return false;                       // self-block AND attacked: double duty
        }
        // Occupied by a white unit: the body blocks the square. Whether it is
        // also attacked is immaterial, by convention.
    }
    return true;
}

bool is_model(const Solution& s) {
    if (!is_pure(s)) return false;
    MateInfo mi = mate_info(s);
    for (const auto& p : mi.pieces) {
        if (p.piece.color != Color::White) continue;
        if (p.piece.type == PieceType::King || p.piece.type == PieceType::Pawn) continue;
        if (!participates(mi, p)) return false;
    }
    return true;
}

bool is_ideal(const Solution& s) {
    if (!is_model(s)) return false;
    MateInfo mi = mate_info(s);
    for (const auto& p : mi.pieces) {
        if (p.piece.color == Color::White) {
            if (!participates(mi, p)) return false;         // no exemptions here
        } else {
            if ((int)p.square == mi.bk) continue;           // the mated king participates by definition
            if (!on_field(mi, p.square)) return false;      // a black unit off the field does nothing
        }
    }
    return true;
}

bool is_mirror(const Solution& s) {
    MateInfo mi = mate_info(s);
    if (!mi.valid) return false;
    for (int f : mi.field)
        if (at_square(mi.pieces, f)) return false;
    return true;
}

}  // namespace hm::themes
```

- [ ] **Step 6: Run the tests**

Run: `taskset -c 0-3 cmake --build build -j4 && taskset -c 0-3 ./build/helpmate_tests "[mate]"`
Expected: PASS.

- [ ] **Step 7: Prove the near-miss tests bite**

`pure` drives `model` and `ideal`, so a subtly wrong `pure` propagates to three detectors. Verify the guards are load-bearing: temporarily change `if (a != 1) return false;` to `if (a < 1) return false;` (accepting over-guarded squares), rebuild, run `taskset -c 0-3 ./build/helpmate_tests "[mate]"`.
Expected: "an over-guarded flight square is impure" FAILS. Restore and re-run to green. Repeat for the black-unit branch: change `if (a != 0) return false;` to `if (false) return false;` and confirm "a black unit on an attacked field square is double duty" FAILS.

- [ ] **Step 8: Commit**

```bash
git add src/core/themes/mate_themes.h src/core/themes/mate_themes.cpp \
        src/core/tests/test_mate_themes.cpp src/core/CMakeLists.txt
git commit -m "feat(themes): pure, model, ideal and mirror mates

Every field square must be unavailable for exactly one reason. A black unit
standing on an attacked square is doing double duty; double check attacks the
king's square twice. Both break purity.

ideal is defined operationally -- every black unit other than the king stands
on a field square -- rather than by the usual 'pinned in a way that matters',
which is the same undecidable-locally clause rejected for pure.

Near-miss fixtures carry the weight here: a pure detector that ignores the
double-duty rule passes every positive case.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Line detectors

**Files:**
- Create: `src/core/themes/trajectory.h`, `trajectory.cpp`, `line_themes.h`, `line_themes.cpp`
- Modify: `src/core/CMakeLists.txt`
- Test: `src/core/tests/test_line_themes.cpp`

**Interfaces:**
- Consumes: `hm::Solution`, `hm::Ply`, `hm::final_board` (Task 1); `attackers_of`, `king_field` (Task 2).
- Produces: `hm::themes::Trajectory`, `hm::themes::trajectories(const Solution&)`, and twelve `bool(const Solution&)` functions: `has_promotion`, `has_underpromotion`, `has_excelsior`, `has_excelsior_white`, `has_excelsior_black`, `has_switchback`, `has_closed_walk`, `has_self_block`, `is_single_piece`, `is_single_piece_white`, `is_single_piece_black`, `has_en_passant`.

- [ ] **Step 1: Write the failing test**

Create `src/core/tests/test_line_themes.cpp`:

```cpp
#include "themes/line_themes.h"
#include "themes/trajectory.h"
#include "probe/solution.h"
#include <catch2/catch_test_macros.hpp>

using namespace hm;
using namespace hm::themes;

static int sq(const char* n) { return (n[1] - '1') * 8 + (n[0] - 'a'); }

// Build a Solution by playing UCI-ish moves onto a start FEN. Each entry is
// {from, to, promotion}. The boards are produced by Board::make so `after`,
// captures and en passant are real, not asserted.
struct MoveSpec { const char* from; const char* to; std::optional<PieceType> promo; };

static Solution play(const std::string& fen, const std::vector<MoveSpec>& specs) {
    auto b = Board::from_fen(fen);
    REQUIRE(b);
    Solution s{*b, {}};
    Board cur = *b;
    for (const auto& ms : specs) {
        const Move* found = nullptr;
        auto legal = cur.legal_moves();
        for (const auto& m : legal)
            if ((int)m.from == sq(ms.from) && (int)m.to == sq(ms.to) && m.promotion() == ms.promo)
                found = &m;
        REQUIRE(found != nullptr);     // the fixture asked for an illegal move
        Ply p;
        p.from = found->from; p.to = found->to;
        p.promotion = found->promotion();
        p.is_ep = found->is_ep();
        for (const auto& pp : cur.pieces()) {
            if ((int)pp.square == (int)found->from) p.piece = pp.piece;
            else if ((int)pp.square == (int)found->to) p.captured = pp.piece.type;
        }
        if (p.is_ep) p.captured = PieceType::Pawn;
        cur.make(*found);
        p.is_check = cur.in_check();
        p.after = cur;
        s.plies.push_back(std::move(p));
    }
    return s;
}

TEST_CASE("trajectories chain a unit's squares through the solution",
          "[themes][line]") {
    // White king walks e1-e2-e3; black king shuffles a8-b8.
    auto s = play("k7/8/8/8/8/8/8/4K3 w - - 0 1",
                  {{"e1", "e2", {}}, {"a8", "b8", {}}, {"e2", "e3", {}}});
    auto ts = trajectories(s);
    REQUIRE(ts.size() == 2);
    for (const auto& t : ts) {
        if (t.color == Color::White) {
            REQUIRE(t.squares == std::vector<uint8_t>{(uint8_t)sq("e1"), (uint8_t)sq("e2"),
                                                       (uint8_t)sq("e3")});
        } else {
            REQUIRE(t.squares.size() == 2);
        }
    }
}

TEST_CASE("promotion and underpromotion", "[themes][line]") {
    auto queen  = play("k7/8/8/8/8/8/6P1/4K3 w - - 0 1",
                       {{"g2", "g4", {}}, {"a8", "b8", {}}, {"g4", "g5", {}},
                        {"b8", "a8", {}}, {"g5", "g6", {}}, {"a8", "b8", {}},
                        {"g6", "g7", {}}, {"b8", "a8", {}}, {"g7", "g8", PieceType::Queen}});
    REQUIRE(has_promotion(queen));
    REQUIRE_FALSE(has_underpromotion(queen));

    auto knight = play("k7/8/8/8/8/8/6P1/4K3 w - - 0 1",
                       {{"g2", "g4", {}}, {"a8", "b8", {}}, {"g4", "g5", {}},
                        {"b8", "a8", {}}, {"g5", "g6", {}}, {"a8", "b8", {}},
                        {"g6", "g7", {}}, {"b8", "a8", {}}, {"g7", "g8", PieceType::Knight}});
    REQUIRE(has_promotion(knight));
    REQUIRE(has_underpromotion(knight));
}

TEST_CASE("excelsior: a pawn from its own second rank promotes",
          "[themes][line]") {
    auto s = play("k7/8/8/8/8/8/6P1/4K3 w - - 0 1",
                  {{"g2", "g4", {}}, {"a8", "b8", {}}, {"g4", "g5", {}},
                   {"b8", "a8", {}}, {"g5", "g6", {}}, {"a8", "b8", {}},
                   {"g6", "g7", {}}, {"b8", "a8", {}}, {"g7", "g8", PieceType::Queen}});
    REQUIRE(has_excelsior(s));
    REQUIRE(has_excelsior_white(s));
    REQUIRE_FALSE(has_excelsior_black(s));

    // Near-miss: same promotion, but the pawn starts on g4, not its home rank.
    auto near = play("k7/8/8/8/6P1/8/8/4K3 w - - 0 1",
                     {{"g4", "g5", {}}, {"a8", "b8", {}}, {"g5", "g6", {}},
                      {"b8", "a8", {}}, {"g6", "g7", {}}, {"a8", "b8", {}},
                      {"g7", "g8", PieceType::Queen}});
    REQUIRE(has_promotion(near));
    REQUIRE_FALSE(has_excelsior(near));
}

TEST_CASE("switchback is out-and-back with exactly one intermediate square",
          "[themes][line]") {
    auto s = play("k7/8/8/8/8/8/8/4K3 w - - 0 1",
                  {{"e1", "e2", {}}, {"a8", "b8", {}}, {"e2", "e1", {}}});
    REQUIRE(has_switchback(s));
    REQUIRE_FALSE(has_closed_walk(s));
}

TEST_CASE("closed walk is a circuit of two or more intermediate squares",
          "[themes][line]") {
    // e1-e2-d2-d1-e1: three intermediate squares, none repeated.
    auto s = play("k7/8/8/8/8/8/8/4K3 w - - 0 1",
                  {{"e1", "e2", {}}, {"a8", "b8", {}}, {"e2", "d2", {}},
                   {"b8", "a8", {}}, {"d2", "d1", {}}, {"a8", "b8", {}},
                   {"d1", "e1", {}}});
    REQUIRE(has_closed_walk(s));
    REQUIRE_FALSE(has_switchback(s));
}

TEST_CASE("a unit that never returns shows neither walk theme",
          "[themes][line]") {
    auto s = play("k7/8/8/8/8/8/8/4K3 w - - 0 1",
                  {{"e1", "e2", {}}, {"a8", "b8", {}}, {"e2", "e3", {}}});
    REQUIRE_FALSE(has_switchback(s));
    REQUIRE_FALSE(has_closed_walk(s));
}

TEST_CASE("single-piece is evaluated per side", "[themes][line]") {
    // White moves only its king; Black moves only its king.
    auto both = play("k7/8/8/8/8/8/8/4K3 w - - 0 1",
                     {{"e1", "e2", {}}, {"a8", "b8", {}}, {"e2", "e3", {}}});
    REQUIRE(is_single_piece_white(both));
    REQUIRE(is_single_piece_black(both));
    REQUIRE(is_single_piece(both));

    // White moves king then rook: two white units.
    auto two = play("k7/8/8/8/8/8/8/R3K3 w - - 0 1",
                    {{"e1", "e2", {}}, {"a8", "b8", {}}, {"a1", "a4", {}}});
    REQUIRE_FALSE(is_single_piece_white(two));
    REQUIRE(is_single_piece_black(two));
    REQUIRE(is_single_piece(two));            // "either side" still holds
}

TEST_CASE("en passant is recognised", "[themes][line]") {
    // White pawn e5, black plays d7-d5, White captures exd6 e.p.
    auto s = play("k7/3p4/8/4P3/8/8/8/4K3 b - - 0 1",
                  {{"d7", "d5", {}}, {"e5", "d6", {}}});
    REQUIRE(s.plies.back().is_ep);
    REQUIRE(has_en_passant(s));
    REQUIRE(s.plies.back().captured == PieceType::Pawn);

    auto quiet = play("k7/8/8/8/8/8/8/4K3 w - - 0 1", {{"e1", "e2", {}}});
    REQUIRE_FALSE(has_en_passant(quiet));
}

TEST_CASE("self-block: a black unit steps onto an unattacked flight square",
          "[themes][line]") {
    // Black rook comes to g8 beside its own king on h8, blocking the flight
    // square, and White mates along the 7th... the rook is not attacked.
    auto s = play("6kr/8/8/8/8/8/6R1/K6R b - - 0 1",
                  {{"h8", "g8", {}}, {"h1", "h8", {}}});
    REQUIRE(has_self_block(s));
}

TEST_CASE("a black unit already beside its king is not a self-block",
          "[themes][line]") {
    // Nothing moved onto the field square during the solution.
    auto s = play("6kr/8/8/8/8/8/8/K5RR w - - 0 1", {{"g1", "g7", {}}});
    REQUIRE_FALSE(has_self_block(s));
}

TEST_CASE("an empty solution shows no line theme", "[themes][line]") {
    auto b = Board::from_fen("R5k1/5K2/8/8/8/8/8/8 b - - 0 1");
    REQUIRE(b);
    Solution s{*b, {}};
    REQUIRE_FALSE(has_promotion(s));
    REQUIRE_FALSE(has_underpromotion(s));
    REQUIRE_FALSE(has_excelsior(s));
    REQUIRE_FALSE(has_switchback(s));
    REQUIRE_FALSE(has_closed_walk(s));
    REQUIRE_FALSE(has_self_block(s));
    REQUIRE_FALSE(has_en_passant(s));
    REQUIRE_FALSE(is_single_piece(s));   // no side moved at all
}
```

**Note for the implementer:** the fixtures above are hand-written and some may need adjusting — `play()` asserts every move is legal, so an illegal fixture fails loudly rather than silently testing nothing. If a fixture rejects, fix the FEN or the move list, not the detector. The self-block fixtures in particular must be checked: confirm with `final_board(s).state()` or by inspection that the black rook really is unattacked on g8 in the positive case. If a fixture cannot be made to work, replace it with one that can and say so in the commit message.

- [ ] **Step 2: Run test to verify it fails**

Add `themes/trajectory.cpp` and `themes/line_themes.cpp` to `HELPMATE_SOURCES`, and `tests/test_line_themes.cpp` to `helpmate_tests`.

Run: `taskset -c 0-3 cmake --build build -j4 2>&1 | tail -20`
Expected: FAIL — `themes/line_themes.h: No such file or directory`

- [ ] **Step 3: Write the trajectory header and implementation**

Create `src/core/themes/trajectory.h`:

```cpp
#pragma once
#include "probe/solution.h"
#include <vector>

namespace hm::themes {

// The path one unit takes through a solution: the squares it occupied in
// order, and the indices of the plies that moved it.
struct Trajectory {
    Color color = Color::White;
    std::vector<uint8_t> squares;   // origin first, final square last
    std::vector<int> plies;         // size == squares.size() - 1
    bool promoted = false;          // one of its plies promoted
};

// One entry per unit that moved at least once, in order of first movement.
// Units are chained by square: a ply moving from a square a tracked unit
// currently occupies continues that unit's trajectory.
std::vector<Trajectory> trajectories(const Solution& s);

}  // namespace hm::themes
```

Create `src/core/themes/trajectory.cpp`:

```cpp
#include "themes/trajectory.h"
#include <array>

namespace hm::themes {

std::vector<Trajectory> trajectories(const Solution& s) {
    std::vector<Trajectory> out;
    // where[colour][square] -> index into `out`, or -1 for "no tracked unit".
    std::array<std::array<int, 64>, 2> where;
    where[0].fill(-1);
    where[1].fill(-1);

    for (int i = 0; i < (int)s.plies.size(); ++i) {
        const Ply& p = s.plies[i];
        const int c = (int)p.piece.color;
        int t = where[c][p.from];
        if (t < 0) {
            out.push_back(Trajectory{p.piece.color, {p.from}, {}, false});
            t = (int)out.size() - 1;
        }
        where[c][p.from] = -1;

        // A captured unit stops existing; drop its entry so a later unit of
        // that colour arriving on the square cannot inherit its trajectory.
        if (p.captured) {
            const int gone = p.is_ep ? (sq_rank(p.from) * 8 + sq_file(p.to)) : (int)p.to;
            where[1 - c][gone] = -1;
        }

        out[t].squares.push_back(p.to);
        out[t].plies.push_back(i);
        if (p.promotion) out[t].promoted = true;
        where[c][p.to] = t;
    }
    return out;
}

}  // namespace hm::themes
```

- [ ] **Step 4: Write the line-themes header**

Create `src/core/themes/line_themes.h`:

```cpp
#pragma once
#include "probe/solution.h"

namespace hm::themes {

// Detectors that walk one solution's plies. All share the Detector signature.

bool has_promotion(const Solution& s);       // any ply promotes a pawn
bool has_underpromotion(const Solution& s);  // any ply promotes to R, B or N

// A pawn standing on its OWN second rank at the start of the solution
// promotes during it.
bool has_excelsior(const Solution& s);
bool has_excelsior_white(const Solution& s);
bool has_excelsior_black(const Solution& s);

// A unit leaves a square and returns to it, having visited exactly one
// intermediate square (out and back).
bool has_switchback(const Solution& s);

// Rundlauf: a unit returns to its departure square having visited two or more
// DISTINCT intermediate squares, traversing a circuit rather than retracing
// its path. Mutually exclusive with switchback for a given return event, but
// one solution may show both, by different units.
bool has_closed_walk(const Solution& s);

// A black unit other than the king moves onto a square of the black king's
// field, and in the mating position that square holds that unit and is NOT
// attacked by White.
bool has_self_block(const Solution& s);

// Every move by that side is made by the same unit.
bool is_single_piece_white(const Solution& s);
bool is_single_piece_black(const Solution& s);
bool is_single_piece(const Solution& s);     // either side

bool has_en_passant(const Solution& s);      // any ply is an en-passant capture

}  // namespace hm::themes
```

- [ ] **Step 5: Write the line-themes implementation**

Create `src/core/themes/line_themes.cpp`:

```cpp
#include "themes/line_themes.h"
#include "themes/attack.h"
#include "themes/trajectory.h"
#include <set>

namespace hm::themes {
namespace {

bool excelsior_for(const Solution& s, std::optional<Color> want) {
    const auto start_pieces = s.start.pieces();
    for (const auto& t : trajectories(s)) {
        if (!t.promoted) continue;
        if (want && t.color != *want) continue;
        const int home = (t.color == Color::White) ? 1 : 6;   // own second rank, 0-indexed
        const uint8_t origin = t.squares.front();
        if (sq_rank(origin) != home) continue;
        for (const auto& p : start_pieces)
            if (p.square == origin && p.piece.color == t.color && p.piece.type == PieceType::Pawn)
                return true;
    }
    return false;
}

bool single_for(const Solution& s, Color c) {
    int n = 0;
    for (const auto& t : trajectories(s))
        if (t.color == c) ++n;
    return n == 1;
}

}  // namespace

bool has_promotion(const Solution& s) {
    for (const auto& p : s.plies)
        if (p.promotion) return true;
    return false;
}

bool has_underpromotion(const Solution& s) {
    for (const auto& p : s.plies)
        if (p.promotion && *p.promotion != PieceType::Queen) return true;
    return false;
}

bool has_excelsior(const Solution& s) { return excelsior_for(s, std::nullopt); }
bool has_excelsior_white(const Solution& s) { return excelsior_for(s, Color::White); }
bool has_excelsior_black(const Solution& s) { return excelsior_for(s, Color::Black); }

bool has_switchback(const Solution& s) {
    for (const auto& t : trajectories(s))
        for (size_t i = 0; i + 2 < t.squares.size(); ++i)
            if (t.squares[i] == t.squares[i + 2]) return true;
    return false;
}

bool has_closed_walk(const Solution& s) {
    for (const auto& t : trajectories(s))
        for (size_t i = 0; i < t.squares.size(); ++i)
            for (size_t j = i + 3; j < t.squares.size(); ++j) {
                if (t.squares[i] != t.squares[j]) continue;
                std::set<uint8_t> mid(t.squares.begin() + i + 1, t.squares.begin() + j);
                if (mid.size() >= 2 && mid.count(t.squares[i]) == 0) return true;
            }
    return false;
}

bool has_self_block(const Solution& s) {
    const auto ps = final_board(s).pieces();
    int bk = -1;
    for (const auto& p : ps)
        if (p.piece.type == PieceType::King && p.piece.color == Color::Black) bk = p.square;
    if (bk < 0) return false;

    for (int f : king_field(bk)) {
        const PlacedPiece* occ = nullptr;
        for (const auto& p : ps)
            if ((int)p.square == f) occ = &p;
        if (!occ || occ->piece.color != Color::Black || occ->piece.type == PieceType::King) continue;
        // Same king-removed rule as is_pure: a blocked square that White also
        // attacks is not a self-block, it is double duty.
        if (attackers_of(ps, Color::White, f, Color::Black) != 0) continue;
        for (const auto& ply : s.plies)                        // did a black unit MOVE there?
            if (ply.piece.color == Color::Black && (int)ply.to == f) return true;
    }
    return false;
}

bool is_single_piece_white(const Solution& s) { return single_for(s, Color::White); }
bool is_single_piece_black(const Solution& s) { return single_for(s, Color::Black); }
bool is_single_piece(const Solution& s) {
    return is_single_piece_white(s) || is_single_piece_black(s);
}

bool has_en_passant(const Solution& s) {
    for (const auto& p : s.plies)
        if (p.is_ep) return true;
    return false;
}

}  // namespace hm::themes
```

- [ ] **Step 6: Run the tests**

Run: `taskset -c 0-3 cmake --build build -j4 && taskset -c 0-3 ./build/helpmate_tests "[line]"`
Expected: PASS. If a `play()` fixture rejects a move as illegal, fix the fixture.

- [ ] **Step 7: Prove the excelsior near-miss bites**

Temporarily drop the `if (sq_rank(origin) != home) continue;` line, rebuild, run `taskset -c 0-3 ./build/helpmate_tests "[line]"`.
Expected: "excelsior: a pawn from its own second rank promotes" FAILS on the near-miss assertion. Restore and confirm green.

- [ ] **Step 8: Commit**

```bash
git add src/core/themes/trajectory.h src/core/themes/trajectory.cpp \
        src/core/themes/line_themes.h src/core/themes/line_themes.cpp \
        src/core/tests/test_line_themes.cpp src/core/CMakeLists.txt
git commit -m "feat(themes): the eight ply-based detectors

Trajectories are the shared primitive: chain each unit's squares through the
solution by from/to, and switchback, closed walk, excelsior and single-piece
all fall out of the resulting paths. Captured units are dropped from the chain
so a later arrival on the same square cannot inherit a dead unit's history.

self-block reuses is_pure's king-removed attack rule: a blocked field square
that White also attacks is double duty, not a self-block.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: The registry and `helpmate themes`

**Files:**
- Create: `src/core/themes/registry.h`, `src/core/themes/registry.cpp`
- Modify: `src/core/CMakeLists.txt`, `src/packages/cli/main.cpp`, `src/packages/cli/CMakeLists.txt`
- Test: `src/core/tests/test_themes_registry.cpp`

**Interfaces:**
- Consumes: everything from Tasks 3 and 4.
- Produces: `hm::themes::Detector` (`bool (*)(const Solution&)`), `hm::themes::ThemeDef{name, fn, doc}`, `theme_registry() -> const std::vector<ThemeDef>&`, `find_theme(std::string_view) -> const ThemeDef*`, `detect(const std::vector<Solution>&) -> std::vector<std::string>`. Tasks 6, 7 and 8 all consume these.

- [ ] **Step 1: Write the failing test**

Create `src/core/tests/test_themes_registry.cpp`:

```cpp
#include "themes/registry.h"
#include <catch2/catch_test_macros.hpp>
#include <set>

using namespace hm;
using namespace hm::themes;

static Solution at(const std::string& fen) {
    auto b = Board::from_fen(fen);
    REQUIRE(b);
    return Solution{*b, {}};
}

TEST_CASE("the registry holds all sixteen entries", "[themes][registry]") {
    REQUIRE(theme_registry().size() == 16);
}

TEST_CASE("every entry has a name, a detector and a doc", "[themes][registry]") {
    for (const auto& t : theme_registry()) {
        REQUIRE_FALSE(t.name.empty());
        REQUIRE(t.fn != nullptr);
        REQUIRE_FALSE(t.doc.empty());
    }
}

TEST_CASE("names are unique", "[themes][registry]") {
    std::set<std::string_view> seen;
    for (const auto& t : theme_registry()) REQUIRE(seen.insert(t.name).second);
}

TEST_CASE("every documented theme is findable by name", "[themes][registry]") {
    for (const char* n : {"pure", "model", "ideal", "mirror", "promotion",
                          "underpromotion", "excelsior", "excelsior:white",
                          "excelsior:black", "switchback", "closed-walk",
                          "self-block", "single-piece", "single-piece:white",
                          "single-piece:black", "en-passant"})
        REQUIRE(find_theme(n) != nullptr);
}

TEST_CASE("an unknown name is not found", "[themes][registry]") {
    REQUIRE(find_theme("rundlauf") == nullptr);   // the English name is closed-walk
    REQUIRE(find_theme("") == nullptr);
    REQUIRE(find_theme("PURE") == nullptr);       // matching is exact, not case-folded
}

TEST_CASE("detect uses any semantics across solutions", "[themes][registry]") {
    auto model_mate = at("R5k1/5K2/8/8/8/8/8/8 b - - 0 1");
    auto not_mate   = at("8/8/8/8/8/8/8/K6k w - - 0 1");

    auto only_second = detect({not_mate, model_mate});
    REQUIRE(std::find(only_second.begin(), only_second.end(), "model") != only_second.end());

    auto neither = detect({not_mate});
    REQUIRE(std::find(neither.begin(), neither.end(), "model") == neither.end());
}

TEST_CASE("detect returns names in registry order", "[themes][registry]") {
    auto names = detect({at("R5k1/5K2/8/8/8/8/8/8 b - - 0 1")});
    size_t prev = 0;
    for (const auto& n : names) {
        size_t idx = 0;
        while (theme_registry()[idx].name != n) ++idx;
        REQUIRE(idx >= prev);
        prev = idx;
    }
}

TEST_CASE("detect on an empty solution set finds nothing", "[themes][registry]") {
    REQUIRE(detect({}).empty());
}
```

Add `#include <algorithm>` at the top of the test file.

- [ ] **Step 2: Run test to verify it fails**

Add `themes/registry.cpp` to `HELPMATE_SOURCES` and `tests/test_themes_registry.cpp` to `helpmate_tests`.

Run: `taskset -c 0-3 cmake --build build -j4 2>&1 | tail -20`
Expected: FAIL — `themes/registry.h: No such file or directory`

- [ ] **Step 3: Write the registry header**

Create `src/core/themes/registry.h`:

```cpp
#pragma once
#include "probe/solution.h"
#include <string>
#include <string_view>
#include <vector>

namespace hm::themes {

// A detector is a PURE function of a solution: no table access, no I/O. Every
// one is therefore testable against a hand-built position with no .hm file,
// and adding a theme is one function plus one registry entry.
using Detector = bool (*)(const Solution&);

struct ThemeDef {
    std::string_view name;
    Detector fn;
    std::string_view doc;   // the definition, shown by `helpmate themes`
};

// Every detector this build knows, in display order. CLI, API and dashboard
// all enumerate this rather than hard-coding names, so none of them needs
// touching when a theme is added.
const std::vector<ThemeDef>& theme_registry();

// nullptr when `name` is not registered. Matching is exact -- no case folding,
// no aliases: a near-miss should be an error naming the valid options, not a
// silent guess.
const ThemeDef* find_theme(std::string_view name);

// Names of every theme shown by AT LEAST ONE of `sols` -- the `any` semantics
// the query surface uses. Returned in registry order.
std::vector<std::string> detect(const std::vector<Solution>& sols);

}  // namespace hm::themes
```

- [ ] **Step 4: Write the registry implementation**

Create `src/core/themes/registry.cpp`:

```cpp
#include "themes/registry.h"
#include "themes/line_themes.h"
#include "themes/mate_themes.h"

namespace hm::themes {

const std::vector<ThemeDef>& theme_registry() {
    static const std::vector<ThemeDef> kRegistry = {
        {"pure", &is_pure,
         "Pure mate: every square of the black king's field is unavailable for "
         "exactly one reason, and the king's square is attacked exactly once "
         "(so double check is impure)."},
        {"model", &is_model,
         "Model mate: pure, and every white unit except the king and pawns "
         "participates -- attacks the king's square or a field square, or "
         "stands on one."},
        {"ideal", &is_ideal,
         "Ideal mate: model with no exemptions -- the white king and white "
         "pawns must participate too, and every black unit other than the king "
         "must stand on a field square."},
        {"mirror", &is_mirror,
         "Mirror mate: every square adjacent to the black king is empty, of "
         "either colour."},
        {"promotion", &has_promotion, "A pawn promotes during the solution."},
        {"underpromotion", &has_underpromotion,
         "A pawn promotes to rook, bishop or knight."},
        {"excelsior", &has_excelsior,
         "A pawn standing on its own second rank at the start of the solution "
         "promotes during it (either colour)."},
        {"excelsior:white", &has_excelsior_white, "Excelsior by a white pawn."},
        {"excelsior:black", &has_excelsior_black, "Excelsior by a black pawn."},
        {"switchback", &has_switchback,
         "A unit leaves a square and returns to it, having visited exactly one "
         "intermediate square."},
        {"closed-walk", &has_closed_walk,
         "Rundlauf: a unit returns to its departure square having visited two "
         "or more distinct intermediate squares, so it traverses a circuit "
         "rather than retracing its path."},
        {"self-block", &has_self_block,
         "A black unit other than the king moves onto a square of its own "
         "king's field and stands there unattacked in the mating position, "
         "blocking a flight square."},
        {"single-piece", &is_single_piece,
         "Every move by one side is made by the same unit (either side)."},
        {"single-piece:white", &is_single_piece_white,
         "Every white move is made by the same unit."},
        {"single-piece:black", &is_single_piece_black,
         "Every black move is made by the same unit; with the king, this is "
         "the Analyzer's 'BK moves only'."},
        {"en-passant", &has_en_passant, "A ply is an en-passant capture."},
    };
    return kRegistry;
}

const ThemeDef* find_theme(std::string_view name) {
    for (const auto& t : theme_registry())
        if (t.name == name) return &t;
    return nullptr;
}

std::vector<std::string> detect(const std::vector<Solution>& sols) {
    std::vector<std::string> out;
    for (const auto& t : theme_registry())
        for (const auto& s : sols)
            if (t.fn(s)) {
                out.emplace_back(t.name);
                break;                        // `any`: one solution is enough
            }
    return out;
}

}  // namespace hm::themes
```

- [ ] **Step 5: Run the registry tests**

Run: `taskset -c 0-3 cmake --build build -j4 && taskset -c 0-3 ./build/helpmate_tests "[registry]"`
Expected: PASS, 8 test cases.

- [ ] **Step 6: Add the `helpmate themes` command**

In `src/packages/cli/main.cpp`, add `#include "themes/registry.h"` beside the existing includes. Then add this function above `main()`:

```cpp
// helpmate themes -- print the detector registry. The vocabulary has to be
// discoverable without the docs, and each entry carries its own definition so
// a disagreement about what a theme means is visible right here.
int cmd_themes() {
    for (const auto& t : themes::theme_registry()) {
        std::cout << t.name << "\n";
        // Wrap the doc at ~72 columns under a 4-space indent.
        std::string doc(t.doc);
        size_t pos = 0;
        while (pos < doc.size()) {
            size_t take = std::min<size_t>(72, doc.size() - pos);
            if (pos + take < doc.size()) {
                size_t sp = doc.rfind(' ', pos + take);
                if (sp != std::string::npos && sp > pos) take = sp - pos;
            }
            std::cout << "    " << doc.substr(pos, take) << "\n";
            pos += take;
            while (pos < doc.size() && doc[pos] == ' ') ++pos;
        }
    }
    return 0;
}
```

In `main()`'s dispatch block, add before the `unknown command` fallthrough:

```cpp
        if (cmd == "themes") return cmd_themes();
```

In `usage()`, add to the command list (after the `mine` line):

```cpp
                 "  helpmate themes\n"
```

and to the command descriptions (after the `mine` description):

```cpp
                 "  themes List every theme detector this build knows, each with the\n"
                 "         definition it uses. These names are what --theme accepts.\n"
```

- [ ] **Step 7: Register a ctest case**

In `src/packages/cli/CMakeLists.txt`, add beside the other `add_test` calls:

```cmake
add_test(NAME cli_themes COMMAND helpmate themes)
set_tests_properties(cli_themes PROPERTIES PASS_REGULAR_EXPRESSION "closed-walk")
```

- [ ] **Step 8: Run the CLI tests**

Run: `taskset -c 0-3 cmake --build build -j4 && taskset -c 0-3 ctest --test-dir build --output-on-failure -R "^cli_themes$"`
Expected: PASS.

Run: `taskset -c 0-3 ./build/helpmate themes | head -20`
Expected: `pure` followed by its wrapped definition, then `model`, and so on.

- [ ] **Step 9: Commit**

```bash
git add src/core/themes/registry.h src/core/themes/registry.cpp \
        src/core/tests/test_themes_registry.cpp src/core/CMakeLists.txt \
        src/packages/cli/main.cpp src/packages/cli/CMakeLists.txt
git commit -m "feat(themes): detector registry and \`helpmate themes\`

Sixteen entries for twelve themes: a bool detector cannot report WHICH side
showed a theme, so excelsior and single-piece carry colour-specific names
beside the broad one. That keeps the signature uniform and makes the query
surface strictly more expressive.

Every entry carries its own definition, printed by \`helpmate themes\`, because
a theme is an aesthetic convention rather than a fact -- a disagreement about
what one means should be visible from the tool, not buried in a spec.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Mining and probing by theme (CLI)

**Files:**
- Modify: `src/core/probe/tablebase.h`, `src/core/probe/tablebase.cpp`
- Modify: `src/packages/cli/main.cpp`, `src/packages/cli/CMakeLists.txt`
- Test: `src/core/tests/test_solutions.cpp` (append), `src/packages/cli/CMakeLists.txt` (ctest cases)

**Interfaces:**
- Consumes: `Tablebase::solutions()` (Task 1), `themes::find_theme`, `themes::Detector`, `themes::detect` (Task 5).
- Produces: `MineFilter::themes` (`std::vector<std::string>`), `hm::shape_of_solutions(int count, const std::vector<Solution>&) -> SolutionShape`, CLI `mine --theme NAME` (repeatable) and `probe --themes`.

- [ ] **Step 1: Write the failing test**

Append to `src/core/tests/test_solutions.cpp`:

```cpp
#include "themes/registry.h"

TEST_CASE("shape_of_solutions agrees with the SAN-based shape_of",
          "[themes][solutions]") {
    Tablebase tb(gen_kqvk());
    auto ls = tb.lines(kGolden, 100);
    auto ss = tb.solutions(kGolden, 100);
    SolutionShape from_san = shape_of(4, ls);
    SolutionShape from_plies = shape_of_solutions(4, ss);
    REQUIRE(from_plies.starts == from_san.starts);
    REQUIRE(from_plies.ends == from_san.ends);
    REQUIRE(from_plies.exhaustive == from_san.exhaustive);
}

TEST_CASE("a saturated count is never enumerated", "[themes][solutions]") {
    REQUIRE_FALSE(shape_of_solutions((int)COUNT_SAT, {}).exhaustive);
}

TEST_CASE("mine filters by theme", "[themes][solutions]") {
    Tablebase tb(gen_kqvk());
    auto m = Material::parse("KQvk");
    REQUIRE(m);

    std::vector<std::string> unfiltered, mirrored;
    tb.mine(*m, MineFilter{.dtm = 2}, [&](const std::string& f) {
        unfiltered.push_back(f); return unfiltered.size() < 400; });
    tb.mine(*m, MineFilter{.dtm = 2, .themes = {"mirror"}}, [&](const std::string& f) {
        mirrored.push_back(f); return mirrored.size() < 400; });

    REQUIRE_FALSE(unfiltered.empty());
    REQUIRE_FALSE(mirrored.empty());
    REQUIRE(mirrored.size() < unfiltered.size());     // the filter must bite
    // Every hit really shows the theme.
    for (const auto& f : mirrored) {
        auto sols = tb.solutions(f, 100);
        bool any = false;
        for (const auto& s : sols) if (themes::is_mirror(s)) any = true;
        REQUIRE(any);
    }
}

TEST_CASE("multiple themes AND together", "[themes][solutions]") {
    Tablebase tb(gen_kqvk());
    auto m = Material::parse("KQvk");
    size_t one = 0, both = 0;
    tb.mine(*m, MineFilter{.dtm = 2, .themes = {"mirror"}},
            [&](const std::string&) { ++one; return one < 400; });
    tb.mine(*m, MineFilter{.dtm = 2, .themes = {"mirror", "model"}},
            [&](const std::string&) { ++both; return both < 400; });
    REQUIRE(both <= one);
}

TEST_CASE("an unknown theme name is rejected, never ignored",
          "[themes][solutions]") {
    Tablebase tb(gen_kqvk());
    auto m = Material::parse("KQvk");
    REQUIRE_THROWS_AS(
        tb.mine(*m, MineFilter{.dtm = 2, .themes = {"nosuchtheme"}},
                [](const std::string&) { return false; }),
        std::invalid_argument);
}
```

Add `#include "themes/mate_themes.h"` to the test file's includes.

- [ ] **Step 2: Run test to verify it fails**

Run: `taskset -c 0-3 cmake --build build -j4 2>&1 | tail -20`
Expected: FAIL — `no member named 'themes' in 'hm::MineFilter'`

- [ ] **Step 3: Extend MineFilter and declare shape_of_solutions**

In `src/core/probe/tablebase.h`, add to `MineFilter` (after `ends`):

```cpp
    // Theme names, validated against themes::theme_registry(). A position
    // matches when EVERY listed theme is shown by AT LEAST ONE of its optimal
    // solutions -- `any` within a theme, AND across themes. An unregistered
    // name throws std::invalid_argument rather than being silently dropped.
    std::vector<std::string> themes;
```

Beside the existing `shape_of` declaration, add:

```cpp
// Same as shape_of, from structured solutions. Distinct moves are compared by
// (from, to, promotion) rather than SAN; SAN disambiguation makes the two
// equivalent, and a test pins that they agree.
SolutionShape shape_of_solutions(int count, const std::vector<Solution>& sols);
```

- [ ] **Step 4: Implement shape_of_solutions and rewrite mine's enumeration branch**

In `src/core/probe/tablebase.cpp`, add `#include "themes/registry.h"` and `#include <array>` at the top. Add after `shape_of`:

```cpp
SolutionShape shape_of_solutions(int count, const std::vector<Solution>& sols) {
    if (count >= (int)COUNT_SAT) return {0, 0, false};   // cannot enumerate exhaustively
    auto key = [](const Ply& p) {
        return std::array<int, 3>{p.from, p.to, p.promotion ? (int)*p.promotion : -1};
    };
    std::set<std::array<int, 3>> firsts, lasts;
    for (const auto& s : sols) {
        if (s.plies.empty()) continue;                   // dtm 0: already mate, no moves
        firsts.insert(key(s.plies.front()));
        lasts.insert(key(s.plies.back()));
    }
    return {(int)firsts.size(), (int)lasts.size(), true};
}
```

Replace the body of `Tablebase::mine` with:

```cpp
void Tablebase::mine(const Material& m, const MineFilter& f,
                      const std::function<bool(const std::string&)>& cb,
                      uint64_t* skipped_saturated) const {
    const Slice* s = load(m);
    if (!s) throw MissingTableError("no table for " + m.name());
    Color stm = (f.dtm % 2) ? Color::White : Color::Black;  // parity invariant: wtm dtm odd, btm dtm even

    // Resolve theme names ONCE, before the scan: a typo must be an error that
    // names the valid options, not millions of positions filtered by nothing.
    std::vector<themes::Detector> dets;
    for (const auto& n : f.themes) {
        const auto* d = themes::find_theme(n);
        if (!d) throw std::invalid_argument("unknown theme: \"" + n + "\"");
        dets.push_back(d->fn);
    }

    const bool want_shape = f.starts >= 0 || f.ends >= 0;
    const bool want_solutions = want_shape || !dets.empty();
    std::vector<PlacedPiece> pp;
    for (uint64_t c = 0; c < s->index.size(); ++c) {
        ValuePair v = s->reader.get(stm, c);
        if (v.dtm != (uint8_t)f.dtm) continue;
        if (f.count >= 0 && v.count != (uint8_t)f.count) continue;
        if (!s->index.decode(c, pp)) continue;
        std::string fen = Board::from_pieces(pp, stm).fen();
        if (want_solutions) {
            // v.count is this cell's own stored count -- the same number a
            // probe() of `fen` would return, since the FEN was built from this
            // cell of this material and so cannot color-flip. Using it directly
            // saves a redundant table lookup per candidate.
            if (v.count >= COUNT_SAT) {                  // unknowable, never guessed at
                if (skipped_saturated) ++*skipped_saturated;
                continue;
            }
            auto sols = solutions(fen, (int)v.count);
            if (want_shape) {
                SolutionShape sh = shape_of_solutions((int)v.count, sols);
                if (f.starts >= 0 && sh.starts != f.starts) continue;
                if (f.ends >= 0 && sh.ends != f.ends) continue;
            }
            bool all_present = true;
            for (auto d : dets) {                        // AND across themes...
                bool any = false;
                for (const auto& sol : sols)             // ...`any` within one
                    if (d(sol)) { any = true; break; }
                if (!any) { all_present = false; break; }
            }
            if (!all_present) continue;
        }
        if (!cb(fen)) return;
    }
}
```

- [ ] **Step 5: Run the core tests, including the v0.6.2 shape lane**

Run: `taskset -c 0-3 cmake --build build -j4 && taskset -c 0-3 ./build/helpmate_tests "[themes]"`
Expected: PASS.

Run: `taskset -c 0-3 ctest --test-dir build --output-on-failure -R "^cli_mine"`
Expected: PASS — `mine`'s enumeration branch was rewritten, so the existing `--starts`/`--ends` cases are the regression guard. If any fail, the rewrite changed v0.6.2 behaviour and must be fixed before continuing.

- [ ] **Step 6: Add the CLI flags**

In `src/packages/cli/main.cpp`:

Add to `main()`'s locals, beside `std::vector<std::string> pos;`:

```cpp
    std::vector<std::string> theme_names;   // --theme, repeatable
    bool show_themes = false;               // probe --themes
```

Add `"--theme"` to `needs_value`:

```cpp
        return a == "--tables" || a == "--threads" || a == "--dtm" || a == "--count" || a == "--max" ||
               a == "--starts" || a == "--ends" || a == "--block-size" || a == "--theme";
```

Add to the flag chain, before the unknown-option branch:

```cpp
        else if (a == "--theme") theme_names.push_back(args[++i]);
        else if (a == "--themes") show_themes = true;
```

Change the two dispatch lines:

```cpp
        if (cmd == "probe") return cmd_probe(pos, tables, show_themes);
        ...
        if (cmd == "mine")
            return cmd_mine(pos, tables, dtm, count, maxn, starts, ends, starts_given, ends_given,
                            theme_names);
```

- [ ] **Step 7: Wire the flags into cmd_probe and cmd_mine**

Change `cmd_probe`'s signature to `int cmd_probe(const std::vector<std::string>& pos, const std::string& tables, bool show_themes)` and insert before its final `return 0;`:

```cpp
    if (show_themes) {
        // Detection forces solution enumeration, so it stays opt-in: a plain
        // probe must not start paying for a field most callers never read.
        auto names = themes::detect(tb.solutions(pos[0], p->count >= (int)COUNT_SAT ? 100 : p->count));
        std::cout << "themes:";
        if (names.empty()) std::cout << " (none)";
        for (const auto& n : names) std::cout << " " << n;
        std::cout << "\n";
        if (p->count >= (int)COUNT_SAT)
            std::cerr << "note: this position's solution count is saturated (255+); themes were "
                         "detected from the first 100 solutions only\n";
    }
```

Change `cmd_mine`'s signature to take `const std::vector<std::string>& theme_names` as its last parameter, and insert after the `--starts`/`--ends` validation loop:

```cpp
    for (const auto& n : theme_names) {
        if (themes::find_theme(n)) continue;
        std::cerr << "error: unknown theme \"" << n << "\"\nvalid themes:";
        for (const auto& t : themes::theme_registry()) std::cerr << " " << t.name;
        std::cerr << "\nrun: helpmate themes    (for what each one means)\n";
        return 3;
    }
```

and pass the names into the filter:

```cpp
        *m, MineFilter{.dtm = dtm, .count = count, .starts = starts, .ends = ends,
                       .themes = theme_names},
```

- [ ] **Step 8: Update `usage()`**

In `usage()`, change the `mine` synopsis line to include the flag and add the flag descriptions after the `--ends` entry:

```cpp
                 "  helpmate mine <MATERIAL> --dtm D [--count C] [--starts N] [--ends N]\n"
                 "                           [--theme NAME]...\n"
```

```cpp
                 "  --theme NAME   mine: only positions where at least one optimal solution\n"
                 "                 shows theme NAME. Repeatable; every named theme must be\n"
                 "                 present, though not necessarily in the same solution.\n"
                 "                 `helpmate themes` lists the names and their definitions.\n"
                 "  --themes       probe: also print the themes the position's solutions show\n"
```

and add to the examples block:

```cpp
                 "  helpmate mine KQvk --dtm 2 --theme mirror --max 5 --tables tt\n"
                 "  helpmate probe \"8/7k/5K2/8/8/8/8/6Q1 b - - 0 1\" --themes --tables tt\n"
```

- [ ] **Step 9: Register ctest cases**

In `src/packages/cli/CMakeLists.txt`, add:

```cmake
add_test(NAME cli_mine_theme COMMAND helpmate mine KQvk --dtm 2 --theme mirror --max 5 --tables ${CLI_TT})
add_test(NAME cli_mine_theme_unknown COMMAND helpmate mine KQvk --dtm 2 --theme nosuch --tables ${CLI_TT})
add_test(NAME cli_probe_themes COMMAND helpmate probe "8/7k/5K2/8/8/8/8/6Q1 b - - 0 1" --themes --tables ${CLI_TT})
set_tests_properties(cli_mine_theme PROPERTIES PASS_REGULAR_EXPRESSION "b - - 0 1" DEPENDS cli_gen)
# An unknown theme must fail loudly and name the alternatives -- the --end/--ends
# lesson: a silently discarded filter returns positions that do not match what
# was asked for, with nothing to indicate it.
set_tests_properties(cli_mine_theme_unknown PROPERTIES
  WILL_FAIL TRUE DEPENDS cli_gen)
set_tests_properties(cli_probe_themes PROPERTIES PASS_REGULAR_EXPRESSION "themes:" DEPENDS cli_gen)
```

- [ ] **Step 10: Run the CLI suite**

Run: `taskset -c 0-3 cmake --build build -j4 && taskset -c 0-3 ctest --test-dir build --output-on-failure -R "^cli_"`
Expected: PASS, all cases.

Verify the unknown-theme message by hand:
Run: `taskset -c 0-3 ./build/helpmate mine KQvk --dtm 2 --theme nosuch --tables build/cli_tables; echo "exit=$?"`
Expected: `error: unknown theme "nosuch"` followed by the valid list, `exit=3`.

- [ ] **Step 11: Commit**

```bash
git add src/core/probe/tablebase.h src/core/probe/tablebase.cpp \
        src/core/tests/test_solutions.cpp \
        src/packages/cli/main.cpp src/packages/cli/CMakeLists.txt
git commit -m "feat(mine): filter positions by theme

A position matches when at least one of its optimal solutions shows the theme;
multiple --theme flags AND, not necessarily within one solution. Theme names
are resolved once before the scan, so a typo is an error naming the valid
options rather than millions of positions filtered by nothing.

mine's enumeration branch now builds solutions once and derives both the
shape filters and the themes from them, instead of re-probing per candidate.
The v0.6.2 --starts/--ends ctest cases are the regression guard on that
rewrite.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: Python bindings and HTTP API

**Files:**
- Modify: `src/packages/bindings/pymodule.cpp`, `src/packages/bindings/helpmate/__init__.py`
- Modify: `src/packages/api/helpmate_server/app.py`
- Test: `src/packages/api/tests/test_api_themes.py`, `src/packages/bindings/tests/test_smoke.py` (append)

**Interfaces:**
- Consumes: `themes::theme_registry`, `themes::find_theme`, `themes::detect` (Task 5); `Tablebase::solutions`, `MineFilter::themes` (Tasks 1, 6).
- Produces: `helpmate.themes() -> list[dict]`, `Tablebase.themes(fen) -> list[str]`, `Tablebase.mine(..., themes=[])`, `Tablebase.mine_with_stats(..., themes=[])`; `GET /v1/themes`, `GET /v1/mine?theme=…` (repeatable), `GET /v1/probe?fen=…&themes=true`.

- [ ] **Step 1: Write the failing API test**

Create `src/packages/api/tests/test_api_themes.py`:

```python
"""Theme surfaces: the registry endpoint, theme filtering on mine, and
opt-in annotation on probe."""

GOLDEN = "8/7k/5K2/8/8/8/8/6Q1 b - - 0 1"


def test_themes_endpoint_lists_the_registry(client):
    r = client.get("/v1/themes")
    assert r.status_code == 200
    body = r.json()
    names = [t["name"] for t in body["themes"]]
    assert "model" in names and "closed-walk" in names
    assert len(names) == len(set(names))
    for t in body["themes"]:
        assert t["doc"]          # every entry carries its definition


def test_mine_accepts_a_repeatable_theme_parameter(client):
    r = client.get("/v1/mine", params={"material": "KQvk", "dtm": 2, "max": 5,
                                       "theme": ["mirror"]})
    assert r.status_code == 200
    assert "fens" in r.json()


def test_mine_theme_filter_actually_narrows(client):
    wide = client.get("/v1/mine", params={"material": "KQvk", "dtm": 2, "max": 500}).json()
    narrow = client.get("/v1/mine", params={"material": "KQvk", "dtm": 2, "max": 500,
                                            "theme": ["mirror"]}).json()
    assert len(narrow["fens"]) < len(wide["fens"])
    assert set(narrow["fens"]) <= set(wide["fens"])


def test_unknown_theme_is_a_400_naming_the_valid_ones(client):
    r = client.get("/v1/mine", params={"material": "KQvk", "dtm": 2,
                                       "theme": ["nosuchtheme"]})
    assert r.status_code == 400
    err = r.json()["error"]
    assert err["code"] == "invalid_theme"
    assert "model" in (err.get("hint") or "")


def test_probe_omits_themes_unless_asked(client):
    assert "themes" not in client.get("/v1/probe", params={"fen": GOLDEN}).json()


def test_probe_themes_opt_in(client):
    body = client.get("/v1/probe", params={"fen": GOLDEN, "themes": "true"}).json()
    assert isinstance(body["themes"], list)
```

Check `src/packages/api/tests/conftest.py` for the fixture name that provides a `TestClient` with a generated `KQvk` table; if it is not called `client`, use the name it does provide, and match the style of `test_api_mine.py`.

- [ ] **Step 2: Run test to verify it fails**

Run: `taskset -c 0-3 python -m pytest src/packages/api/tests/test_api_themes.py -x -q 2>&1 | tail -20`
Expected: FAIL — 404 on `/v1/themes`.

- [ ] **Step 3: Extend the pybind11 module**

In `src/packages/bindings/pymodule.cpp`, add `#include "themes/registry.h"` at the top. Add a module-level function beside `mod.def("_perft", ...)`:

```cpp
    mod.def("themes", []() {
        py::list out;
        for (const auto& t : themes::theme_registry()) {
            py::dict d;
            d["name"] = std::string(t.name);
            d["doc"] = std::string(t.doc);
            out.append(std::move(d));
        }
        return out;
    }, "Every theme detector this build knows: [{name, doc}, ...], in display order.");
```

Add a `themes` method to the `Tablebase` class binding, after `moves`:

```cpp
        .def("themes", [](const Tablebase& t, const std::string& fen, int max) {
            return themes::detect(t.solutions(fen, max));
        }, py::arg("fen"), py::arg("max") = 100)
```

Add a `themes` argument to both `mine` and `_mine_with_stats`. For `mine`:

```cpp
        .def("mine", [](const Tablebase& t, const std::string& mat, int dtm, int count,
                        int max, int starts, int ends, std::vector<std::string> themes) {
            validate_mine_shape(count, starts, ends);
            std::vector<std::string> out;
            t.mine(mat_or_throw(mat),
                   MineFilter{.dtm = dtm, .count = count, .starts = starts, .ends = ends,
                              .themes = std::move(themes)},
                   [&](const std::string& f) {
                       out.push_back(f); return (int)out.size() < max; });
            return out;
        }, py::arg("material"), py::arg("dtm"), py::arg("count") = -1, py::arg("max") = 100,
           py::arg("starts") = -1, py::arg("ends") = -1,
           py::arg("themes") = std::vector<std::string>{})
```

and the identical treatment for `_mine_with_stats` (same new parameter, same default, passed into the same field).

- [ ] **Step 4: Update the Python wrapper**

In `src/packages/bindings/helpmate/__init__.py`:

```python
import json as _json
from ._helpmate import (
    Tablebase as _Tablebase, generate, themes, MissingTableError, __version__,
)

class Tablebase(_Tablebase):
    def stats(self, material: str) -> dict:
        return _json.loads(self._stats_json(material))

    def mine_with_stats(self, material: str, dtm: int, count: int = -1, max: int = 100,
                        starts: int = -1, ends: int = -1,
                        themes: list[str] | None = None) -> tuple[list, int]:
        """Like mine(), but also returns how many positions were skipped because
        their optimal-line count is saturated (255+) and therefore not enumerable."""
        return self._mine_with_stats(material, dtm, count, max, starts, ends,
                                     themes or [])

__all__ = ["Tablebase", "generate", "themes", "MissingTableError", "__version__"]
```

- [ ] **Step 5: Add a bindings smoke test**

Append to `src/packages/bindings/tests/test_smoke.py`:

```python
def test_theme_registry_is_exposed():
    import helpmate
    reg = helpmate.themes()
    names = [t["name"] for t in reg]
    assert "model" in names and "en-passant" in names
    assert all(t["doc"] for t in reg)


def test_probe_themes_and_mine_theme_filter(tb):
    golden = "8/7k/5K2/8/8/8/8/6Q1 b - - 0 1"
    assert isinstance(tb.themes(golden), list)
    wide = tb.mine("KQvk", dtm=2, max=500)
    narrow = tb.mine("KQvk", dtm=2, max=500, themes=["mirror"])
    assert set(narrow) <= set(wide)
    assert len(narrow) < len(wide)
```

Use whatever fixture `test_smoke.py` already uses for a generated `KQvk` tablebase in place of `tb` if the name differs.

- [ ] **Step 6: Rebuild the bindings and run their tests**

Run: `GIT_CONFIG_GLOBAL=/dev/null taskset -c 0-3 python -m pip install . -q && taskset -c 0-3 python -m pytest src/packages/bindings/tests -q`
Expected: PASS. (`GIT_CONFIG_GLOBAL=/dev/null` is mandatory — without it pip's isolated build env inherits the HTTPS→SSH rewrite and the FetchContent clone hangs on an invisible passphrase dialog.)

- [ ] **Step 7: Add the API endpoints**

In `src/packages/api/helpmate_server/app.py`:

Add the registry endpoint beside `/v1/materials`:

```python
    @app.get("/v1/themes")
    def themes_list():
        # Served from the core registry so the dashboard never hard-codes a
        # theme list that can drift from the build it is talking to.
        return {"themes": helpmate.themes()}
```

Change `probe` to take the opt-in flag. Its signature becomes `def probe(fen: str, themes: bool = False):`, and before the final `return`:

```python
        out = {"dtm": dtm, "count": count, "flipped": flipped,
               "notation": h_notation(dtm)}
        if themes:
            # Opt-in: detection forces solution enumeration, and /v1/probe is
            # on the dashboard's hot path.
            try:
                out["themes"] = _tb(chain, d).themes(fen)
            except ValueError as e:
                return JSONResponse(status_code=400,
                                    content=error_json("invalid_fen", str(e)))
        return out
```

(replacing the existing `return {"dtm": ...}` line).

Change `mine`'s signature to accept the repeatable parameter, adding `Query` to the FastAPI imports at the top of the file:

```python
    @app.get("/v1/mine")
    def mine(material: str, dtm: int, count: int = -1, max: int = 100,
             starts: Optional[int] = None, ends: Optional[int] = None,
             theme: list[str] = Query(default=[])):
```

and insert this validation immediately after the existing `starts`/`ends` validation loop:

```python
        known = {t["name"] for t in helpmate.themes()}
        for name in theme:
            if name not in known:
                return JSONResponse(status_code=400, content=error_json(
                    "invalid_theme", f"unknown theme: {name}",
                    hint="valid themes: " + ", ".join(t["name"] for t in helpmate.themes())))
```

and pass it through to the worker:

```python
        fut = pool.submit(_tb(chain, d).mine_with_stats, material, dtm, count,
                          clamped + 1, starts, ends, theme)
```

- [ ] **Step 8: Run the API tests**

Run: `taskset -c 0-3 python -m pytest src/packages/api/tests -q`
Expected: PASS — the new file plus every existing case (`mine`'s signature changed, so `test_api_mine.py` is the regression guard).

- [ ] **Step 9: Commit**

```bash
git add src/packages/bindings/pymodule.cpp src/packages/bindings/helpmate/__init__.py \
        src/packages/bindings/tests/test_smoke.py \
        src/packages/api/helpmate_server/app.py \
        src/packages/api/tests/test_api_themes.py
git commit -m "feat(api): theme registry, theme filtering, opt-in annotation

/v1/themes serves the core registry so the dashboard never hard-codes a list
that can drift from the build it is talking to. An unknown theme on /v1/mine
is a 400 naming the valid options, never a silently ignored filter.

Annotation on /v1/probe is opt-in via themes=true: detection forces solution
enumeration and probe is on the dashboard's hot path, so defaulting it on
would make every probe pay for a field most callers never read.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: Dashboard

**Files:**
- Create: `src/packages/web/helpmate_web/static/js/lib/themes.js`
- Test: `src/packages/web/tests/js/themes.test.js`
- Modify: `src/packages/web/helpmate_web/static/js/api.js`, `mine.js`, `explorer.js`
- Modify: `src/packages/web/helpmate_web/static/index.html`, `static/css/app.css`
- Modify: `src/packages/web/tests/ui/test_dashboard.py`

**Interfaces:**
- Consumes: `GET /v1/themes`, `GET /v1/mine?theme=…`, `GET /v1/probe?themes=true` (Task 7).
- Produces: `themeParams(selected) -> URLSearchParams`-compatible entries; a `#mine-themes` multi-select; a themes line in the explorer's position summary.

- [ ] **Step 1: Write the failing JS test**

Create `src/packages/web/tests/js/themes.test.js`:

```js
import { test } from "node:test";
import assert from "node:assert/strict";
import { selectedThemes, themeSummary } from "../../helpmate_web/static/js/lib/themes.js";

test("selectedThemes reads the chosen options off a multi-select", () => {
  const el = {
    selectedOptions: [{ value: "model" }, { value: "mirror" }],
  };
  assert.deepEqual(selectedThemes(el), ["model", "mirror"]);
});

test("selectedThemes returns an empty list for no selection", () => {
  assert.deepEqual(selectedThemes({ selectedOptions: [] }), []);
  assert.deepEqual(selectedThemes(null), []);
});

test("themeSummary lists names, and says so when there are none", () => {
  assert.equal(themeSummary(["model", "mirror"]), "model · mirror");
  assert.equal(themeSummary([]), "no themes detected");
  assert.equal(themeSummary(undefined), "");
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `taskset -c 0-3 node --test src/packages/web/tests/js/themes.test.js 2>&1 | tail -20`
Expected: FAIL — `Cannot find module .../lib/themes.js`

- [ ] **Step 3: Write the helper module**

Create `src/packages/web/helpmate_web/static/js/lib/themes.js`:

```js
// Pure helpers for the theme surfaces. Kept out of mine.js/explorer.js so they
// are testable under `node --test` with no DOM.

// The theme names chosen in a <select multiple>, as a plain array.
export function selectedThemes(el) {
  if (!el || !el.selectedOptions) return [];
  return Array.from(el.selectedOptions, (o) => o.value);
}

// One line of prose for a position's detected themes.
export function themeSummary(names) {
  if (names === undefined || names === null) return "";
  return names.length ? names.join(" · ") : "no themes detected";
}
```

- [ ] **Step 4: Run the JS test**

Run: `taskset -c 0-3 node --test src/packages/web/tests/js/themes.test.js`
Expected: PASS, 3 tests.

- [ ] **Step 5: Add the API wrappers**

In `src/packages/web/helpmate_web/static/js/api.js`, `getJson` builds params with `searchParams.set`, which cannot express a repeatable parameter. Add array support:

```js
export async function getJson(path, params = {}) {
  const url = new URL(path, window.location.origin);
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === "") continue;
    // A repeatable parameter (theme=a&theme=b) needs append, not set.
    if (Array.isArray(v)) { for (const item of v) url.searchParams.append(k, item); continue; }
    url.searchParams.set(k, v);
  }
  ...
```

(keep the rest of the function unchanged), and extend the `api` object:

```js
  probe: (fen, themes = false) => getJson("/v1/probe", { fen, themes: themes ? "true" : "" }),
  themes: () => getJson("/v1/themes"),
```

- [ ] **Step 6: Add the multi-select to the search form**

In `src/packages/web/helpmate_web/static/index.html`, inside `#mine-form`, after the `ends` label and before `max results`:

```html
      <label>themes
        <select id="mine-themes" name="theme" multiple size="6"></select>
        <small class="hint">optional — a position must show every theme you pick, though not necessarily in the same solution</small>
      </label>
```

In `static/css/app.css`, append:

```css
/* The theme picker is taller than the numeric inputs beside it, so let it
   claim its own row rather than stretching the whole form's line height. */
#mine-form select[multiple] { min-width: 14rem; }
#mine-form .hint { display: block; opacity: 0.7; font-size: 0.85em; }
#position-themes { margin-top: 0.25rem; opacity: 0.85; }
```

- [ ] **Step 7: Populate the picker and send the selection**

In `src/packages/web/helpmate_web/static/js/mine.js`, add the import:

```js
import { selectedThemes } from "./lib/themes.js";
```

Add this inside `initMine()`, before the submit listener:

```js
  // Populated from /v1/themes so the vocabulary always matches the server's
  // build. A failure here leaves an empty picker and no theme filtering --
  // the rest of the search screen must keep working.
  const themeSel = document.getElementById("mine-themes");
  api.themes().then(({ body }) => {
    for (const t of body.themes) {
      const o = document.createElement("option");
      o.value = t.name;
      o.textContent = t.name;
      o.title = t.doc;
      themeSel.appendChild(o);
    }
  }).catch(() => { /* leave the picker empty; the numeric filters still work */ });
```

In the submit handler, `Object.fromEntries(new FormData(form).entries())` keeps only the LAST value of a repeated field, so the multi-select must be read separately. Change the handler's first lines to:

```js
    e.preventDefault();
    const q = Object.fromEntries(new FormData(form).entries());
    q.theme = selectedThemes(themeSel);      // fromEntries would keep only one
```

and in `runQuery`, include the chosen themes in each result row so the CSV export carries them:

```js
  rows = b.fens.map((fen) => ({ fen, dtm: Number(q.dtm),
                                count: q.count === "" ? "" : Number(q.count) }));
```

(leave this line as it is — the export schema is unchanged in this rung.)

- [ ] **Step 8: Show themes in the explorer**

In `src/packages/web/helpmate_web/static/index.html`, add immediately after the `#position-summary` element:

```html
      <p id="position-themes" class="verdict"></p>
```

In `src/packages/web/helpmate_web/static/js/explorer.js`, add the import:

```js
import { themeSummary } from "./lib/themes.js";
```

and after the block that sets `summary.textContent` from `/v1/moves`, add:

```js
  const themesEl = document.getElementById("position-themes");
  themesEl.textContent = "";
  if (b.solvable !== false) {
    // A second call, like the /v1/line one below: themes are opt-in on
    // /v1/probe precisely so the moves request stays cheap.
    api.probe(fen, true).then(({ body }) => {
      if (seq !== renderSeq) return;         // superseded by a newer render()
      themesEl.textContent = themeSummary(body.themes);
    }).catch(() => { /* annotation is a nicety; never break the board on it */ });
  }
```

Also clear it in the editing branch (around the existing `summary.textContent = "editing — …"` line):

```js
    document.getElementById("position-themes").textContent = "";
```

- [ ] **Step 9: Add a Playwright assertion**

Append to `src/packages/web/tests/ui/test_dashboard.py`, matching the style of the existing tests in that file:

```python
def test_theme_picker_is_populated_from_the_server(page, base_url):
    page.goto(f"{base_url}/#panel=mine")
    page.wait_for_selector("#mine-themes option")
    values = page.eval_on_selector_all(
        "#mine-themes option", "els => els.map(e => e.value)")
    assert "model" in values and "closed-walk" in values


def test_explorer_shows_detected_themes(page, base_url):
    page.goto(f"{base_url}/#fen=8/7k/5K2/8/8/8/8/6Q1%20b%20-%20-%200%201&panel=explorer")
    page.wait_for_function(
        "() => document.getElementById('position-themes').textContent.length > 0")
    text = page.inner_text("#position-themes")
    assert text  # either a theme list or "no themes detected"
```

If the hash-state format or fixture names in `test_dashboard.py` differ from the above, follow that file's existing conventions rather than these.

- [ ] **Step 10: Run the web tests**

Run: `taskset -c 0-3 node --test src/packages/web/tests/js/`
Expected: PASS, all JS test files.

Run: `GIT_CONFIG_GLOBAL=/dev/null taskset -c 0-3 python -m pip install ./src/packages/web -q && taskset -c 0-3 python -m pytest src/packages/web/tests/ui -q`
Expected: PASS. Playwright must launch with `--no-sandbox` on this box; `conftest.py` already handles that.

- [ ] **Step 11: Verify panel exclusivity did not regress**

The v0.7 dashboard had a bug where `#panel-explorer { display: flex }` outranked the UA's `[hidden]` rule and panels stacked. New markup in a panel is exactly how that returns.

Run: `taskset -c 0-3 python -m pytest src/packages/web/tests/ui -q -k "panel"`
Expected: PASS — the panel-exclusivity assertion added in v0.7 must still hold.

- [ ] **Step 12: Commit**

```bash
git add src/packages/web/helpmate_web/static/js/lib/themes.js \
        src/packages/web/helpmate_web/static/js/api.js \
        src/packages/web/helpmate_web/static/js/mine.js \
        src/packages/web/helpmate_web/static/js/explorer.js \
        src/packages/web/helpmate_web/static/index.html \
        src/packages/web/helpmate_web/static/css/app.css \
        src/packages/web/tests/js/themes.test.js \
        src/packages/web/tests/ui/test_dashboard.py
git commit -m "feat(web): theme picker on search, themes on the explorer

The picker is populated from /v1/themes, so the vocabulary always matches the
server's build and the dashboard never carries a list that can drift. Each
option's title is the detector's own definition.

FormData.entries() keeps only the last value of a repeated field, so the
multi-select is read separately -- otherwise a two-theme search would silently
send one.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 9: Documentation and the version bump

**Files:**
- Modify: `docs/USAGE.md`, `docs/ROADMAP.md`, `README.md`, `VERSION`
- Modify: `docs/superpowers/specs/2026-08-03-theme-detection-design.md` (status line)

**Interfaces:**
- Consumes: everything shipped in Tasks 1–8.
- Produces: no code interfaces; the release-facing description of the rung.

- [ ] **Step 1: Bump the version**

`VERSION` currently reads `0.7.5`. Replace its entire contents with:

```
0.8.0
```

This is the single source of truth — CMake reads it into `project()`, which feeds `version.h` and the `cli_version` test, and the three `pyproject.toml` files are checked against it.

- [ ] **Step 2: Verify the version propagated**

Run: `taskset -c 0-3 cmake -S . -B build && taskset -c 0-3 cmake --build build -j4 && taskset -c 0-3 ./build/helpmate --version`
Expected: `helpmate 0.8.0`

Run: `taskset -c 0-3 ctest --test-dir build --output-on-failure -R "^cli_version$"`
Expected: PASS.

- [ ] **Step 3: Document the themes in `docs/USAGE.md`**

Add a `## Themes` section after the existing `mine` documentation. It must contain: the twelve themes with the definitions from `theme_registry()`; the `any`-within-a-theme / AND-across-themes rule; the three CLI surfaces (`mine --theme`, `probe --themes`, `helpmate themes`); the three API surfaces; and these two caveats stated plainly:

```markdown
### Two things to know before you trust a result

**The solution cap is a false-negative source.** Themes are detected across a
position's optimal solutions, capped at the position's own solution count. A
position whose count is saturated (255+) is never enumerated and never matches
a theme filter; `mine` reports these in its skipped tally rather than dropping
them silently.

**Theme filters are slow on compressed tables.** Detection forces solution
enumeration, which is exactly the random-access pattern that defeats the block
cache — on a compressed table it compounds with the ~6.5x mining penalty
measured in v0.7.5. Mine against raw tables when running theme searches over
large material.
```

Also add a line to the flags table for `--theme` and `--themes`.

- [ ] **Step 4: Update `README.md`**

Add `themes` to the command list wherever `mine`, `probe`, `line`, `stats` and `compact` are enumerated, and add one example beside the existing `mine` example:

```bash
helpmate mine KRvkbn --dtm 8 --theme model --theme self-block --tables ~/tb
```

- [ ] **Step 5: Mark the rung shipped in `docs/ROADMAP.md`**

In the `## v0.8 — Pattern / theme search` section, replace the `**Goal:**` paragraph's forward-looking framing and add a delivery line, keeping the existing Design/Depends/Scoped/Deferred bullets:

```markdown
- **Shipped in v0.8.0.** Twelve themes across CLI (`mine --theme`,
  `probe --themes`, `helpmate themes`), API (`/v1/themes`, `theme=` on
  `/v1/mine`, `themes=true` on `/v1/probe`) and the dashboard.
```

- [ ] **Step 6: Update the spec's status line**

In `docs/superpowers/specs/2026-08-03-theme-detection-design.md`, change:

```
Status: approved by user (brainstorming session 2026-08-03)
```

to:

```
Status: approved by user (brainstorming session 2026-08-03). Implemented in
v0.8.0; see docs/superpowers/plans/2026-08-03-theme-detection.md.
```

- [ ] **Step 7: Run the whole suite**

```bash
taskset -c 0-3 cmake --build build -j4
taskset -c 0-3 ./build/helpmate_tests "~[slow]"
taskset -c 0-3 ctest --test-dir build --output-on-failure
taskset -c 0-3 node --test src/packages/web/tests/js/
GIT_CONFIG_GLOBAL=/dev/null taskset -c 0-3 python -m pip install . ./src/packages/api ./src/packages/web -q
taskset -c 0-3 python -m pytest src/packages/bindings/tests src/packages/api/tests src/packages/web/tests/ui -q
```

Expected: every lane green. Record the actual counts in the commit message — do not write "all tests pass" without the numbers in front of you.

- [ ] **Step 8: Run the PR gate lanes locally**

```bash
taskset -c 0-3 make lint
taskset -c 0-3 make typecheck
taskset -c 0-3 make format-check
```

Expected: clean. These are the same pinned tools CI runs (v0.7.2); an unpinned local version giving a different answer is a known failure mode — if `make format-check` reports nothing at all, confirm `clang-format` is actually on PATH rather than assuming success.

- [ ] **Step 9: Commit**

```bash
git add VERSION docs/USAGE.md docs/ROADMAP.md README.md \
        docs/superpowers/specs/2026-08-03-theme-detection-design.md
git commit -m "docs: v0.8.0 theme detection

Records the two caveats a user has to know before trusting a result: the
solution cap is a false-negative source, and theme filters compound the
compressed-table mining penalty, so large theme searches should run against
raw tables.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage.** Every section of `2026-08-03-theme-detection-design.md` maps to a task: the twelve themes → Tasks 3 and 4; the `Ply`/`Solution` type → Task 1; the `Detector`/`ThemeDef`/`theme_registry()` architecture → Task 5; `any` semantics, AND across themes, saturated-position skipping and the solution cap → Task 6 (core) and Task 7 (API); the three CLI surfaces → Tasks 5 and 6; the three API surfaces → Task 7; the dashboard → Task 8; "no precomputed index" → satisfied by construction, nothing in the plan writes a file; the performance note and the deferred-verification risk → Task 9's documentation. `attack.h` (Task 2) has no counterpart section in the spec — it is the primitive the mate detectors need, and the spec's king-removal rule was added because writing this task exposed it.

**Placeholder scan.** One deliberate placeholder survives, and it is flagged as such: `attackersOfKingIsOne` in Task 3's "double check is impure" test, with an explicit instruction to delete those lines after verifying the fixture. Task 3 Step 2 and Task 4 Step 1 both carry notes telling the implementer to fix a fixture rather than a detector if a hand-written FEN turns out not to be mate or not to be legal — hand-authored chess fixtures are the one thing here that cannot be fully verified without running the code.

**Type consistency.** `Solution{start, plies}` and `final_board()` are defined in Task 1 and used unchanged in Tasks 3, 4, 5, 6. `attackers_of` / `piece_attacks` / `king_field` are defined in Task 2 with the `ignore_king_of` parameter and used with that exact spelling in Tasks 3 and 4. `Detector = bool (*)(const Solution&)` in Task 5 matches the signature of every function declared in Tasks 3 and 4 — checked name by name: `is_pure`, `is_model`, `is_ideal`, `is_mirror`, `has_promotion`, `has_underpromotion`, `has_excelsior{,_white,_black}`, `has_switchback`, `has_closed_walk`, `has_self_block`, `is_single_piece{,_white,_black}`, `has_en_passant` — sixteen, matching the registry-size assertion in Task 5's test. `MineFilter::themes` (Task 6) is the field name used by the pybind11 bindings in Task 7. `shape_of_solutions` is declared and defined in Task 6 and asserted against `shape_of` in the same task.

**One risk worth naming.** Task 6 rewrites `mine()`'s enumeration branch, which v0.6.2's `--starts`/`--ends` filters depend on. That is why Step 5 of that task runs the existing `cli_mine*` ctest cases as a regression gate before the new CLI flags are added, rather than at the end.
