# Helpmate Tablebase Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A C++20 tablebase generator + prober that computes, for every position of a piece combination, the smallest ply distance to a cooperative checkmate of Black ("helpmate DTM") plus the number of distinct optimal lines, with CLI, Python bindings, and stats reports.

**Architecture:** Forward-scan fixed-point BFS over a dense per-slice index (symmetry-reduced), building the full dependency closure of sub-slices (captures/promotions) first. Move generation is delegated to the vendored ChessMG C++ core behind a thin adapter. Spec: `docs/superpowers/specs/2026-07-19-helpmate-tablebase-design.md`.

**Tech Stack:** C++20, CMake ≥3.24, ChessMG (vendored via FetchContent), Catch2 v3, nlohmann/json, pybind11 + scikit-build-core, pytest + python-chess (test oracle).

## Global Constraints

- Platform: Linux/GCC only (POSIX `mmap` is used); C++20; CMake ≥ 3.24.
- Dependencies (all FetchContent-pinned, MIT-compatible): ChessMG @ pinned commit (MIT), Catch2 `v3.5.4` (BSL-1.0), nlohmann/json `v3.11.3` (MIT), pybind11 ≥ 2.12 (BSD).
- ChessMG headers may be included **only** in `src/chess/board.cpp` (they run static initializers in every including TU).
- Value semantics: DTM in plies to "Black is checkmated", both sides cooperate. Black-to-move values are even, White-to-move odd. Sentinels (`src/chess/types.h`): `DTM_UNSET=253` (generation-transient, never on disk), `DTM_INVALID=254`, `DTM_UNSOLVABLE=255`. Solution counts saturate at `COUNT_SAT=255` ("≥255"); count is 0 for invalid/unsolvable cells.
- No castling anywhere; `Board::from_fen` rejects FENs with castling rights. En passant is never indexed; it is resolved on the fly by `eval_board` (Task 10).
- Slice naming: canonical form like `KQvk` / `KBvkqrbp` — white pieces sorted K,Q,R,B,N,P, then `v`, then black pieces likewise. Files: `tables/<NAME>.hm` + `tables/<NAME>.stats.json`.
- TDD throughout: write the failing test first, watch it fail, implement, watch it pass, commit. All commits end with `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.
- Definition of done: `ctest` green, pytest green, line coverage ≥ 80 % on `src/` (Task 19).
- Hand-verified golden values in tests: if the oracle or generator disagrees with a hand-verified expectation, STOP and re-verify by hand on a board before changing either side — do not silently "fix" the expectation.

## File Structure

```
CMakeLists.txt                    # top level: deps, libs, CLI, tests, bindings
Makefile                          # convenience: build / test / coverage
pyproject.toml                    # scikit-build-core packaging (Task 17)
src/chess/types.h                 # Color, PieceType, Piece, PlacedPiece, Move, PosState, ValuePair, sentinels
src/chess/board.h|.cpp            # Board adapter over ChessMG (ONLY file including ChessMG headers)
src/chess/san.h|.cpp              # SAN formatting
src/indexing/material.h|.cpp      # Material parse/name/successors/closure_topo
src/indexing/kk.h|.cpp            # symmetry transforms + KK tables (1806 / 462)
src/indexing/slice_index.h|.cpp   # SliceIndex: encode/decode, canonicalization
src/format/table_file.h|.cpp      # TableHeader, TableWriter, TableReader (mmap)
src/generator/eval.h              # eval_board<LookupFn> (EP-aware successor evaluation, header-only)
src/generator/oracle.h|.cpp       # cooperative IDDFS oracle (independent verifier)
src/generator/generator.h|.cpp    # SliceGen passes + generate() closure driver
src/probe/tablebase.h|.cpp        # Tablebase: probe/line/lines/mine/stats, color flip
src/cli/main.cpp                  # helpmate CLI
src/bindings/pymodule.cpp         # pybind11 module _helpmate
python/helpmate/__init__.py       # Python wrapper package
tests/cpp/test_*.cpp              # Catch2 suites (one per module)
tests/python/test_*.py            # pytest: smoke, python-chess cross-validation
```

---

### Task 1: Build skeleton and vendored dependencies

**Files:**
- Create: `CMakeLists.txt`, `Makefile`, `tests/cpp/test_sanity.cpp`

**Interfaces:**
- Produces: CMake targets `chessmg_core` (vendored lib), `helpmate_core` (our static lib, initially empty source list grows per task), `helpmate_tests` (Catch2), `helpmate` (CLI, added Task 16). Later tasks append their `.cpp` files to `helpmate_core`/`helpmate_tests` source lists.

- [ ] **Step 1: Pin ChessMG**

Run: `git ls-remote https://github.com/osick/ChessMG.git refs/heads/main | cut -f1`
Copy the SHA; it replaces `<CHESSMG_SHA>` below.

- [ ] **Step 2: Write the failing build (sanity test)**

`tests/cpp/test_sanity.cpp`:
```cpp
#include <catch2/catch_test_macros.hpp>
TEST_CASE("sanity") { REQUIRE(1 + 1 == 2); }
```

`CMakeLists.txt`:
```cmake
cmake_minimum_required(VERSION 3.24)
project(helpmate LANGUAGES CXX)
set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE Release)
endif()
find_package(Threads REQUIRED)

include(FetchContent)
FetchContent_Declare(chessmg
  GIT_REPOSITORY https://github.com/osick/ChessMG.git
  GIT_TAG <CHESSMG_SHA>)
FetchContent_Declare(catch2
  GIT_REPOSITORY https://github.com/catchorg/Catch2.git
  GIT_TAG v3.5.4)
FetchContent_Declare(json
  GIT_REPOSITORY https://github.com/nlohmann/json.git
  GIT_TAG v3.11.3)
FetchContent_MakeAvailable(chessmg catch2 json)

add_library(chessmg_core STATIC
  ${chessmg_SOURCE_DIR}/chessmg/libcmg/libsurge.cpp
  ${chessmg_SOURCE_DIR}/chessmg/libcmg/libcmg.cpp)
target_include_directories(chessmg_core SYSTEM PUBLIC ${chessmg_SOURCE_DIR}/chessmg/libcmg)
target_compile_options(chessmg_core PRIVATE -O2 -w)

set(HELPMATE_SOURCES "")           # tasks append here
add_library(helpmate_core STATIC ${HELPMATE_SOURCES} src/placeholder.cpp)
target_include_directories(helpmate_core PUBLIC src)
target_link_libraries(helpmate_core PUBLIC chessmg_core nlohmann_json::nlohmann_json Threads::Threads)
target_compile_options(helpmate_core PRIVATE -O2 -Wall -Wextra)

enable_testing()
add_executable(helpmate_tests tests/cpp/test_sanity.cpp)
target_link_libraries(helpmate_tests PRIVATE helpmate_core Catch2::Catch2WithMain)
list(APPEND CMAKE_MODULE_PATH ${catch2_SOURCE_DIR}/extras)
include(Catch)
catch_discover_tests(helpmate_tests)
```

`src/placeholder.cpp` (deleted in Task 2 when real sources exist):
```cpp
namespace hm { int placeholder() { return 0; } }
```

`Makefile`:
```make
BUILD ?= build
.PHONY: configure build test coverage clean
configure:
	cmake -S . -B $(BUILD)
build: configure
	cmake --build $(BUILD) -j
test: build
	ctest --test-dir $(BUILD) --output-on-failure
clean:
	rm -rf $(BUILD)
```

- [ ] **Step 3: Build and run**

Run: `make test`
Expected: ChessMG/Catch2/json are fetched, everything compiles, `sanity` test PASSES. If `libsurge.cpp`/`libcmg.cpp` fail to compile standalone, fix include paths only in `chessmg_core` (do not patch vendored sources; if a real ChessMG bug blocks the build, report upstream and STOP for user input).

- [ ] **Step 4: Commit**

```bash
git add CMakeLists.txt Makefile src/placeholder.cpp tests/cpp/test_sanity.cpp
git commit -m "build: CMake skeleton with vendored ChessMG, Catch2, nlohmann/json"
```

---

### Task 2: Chess adapter — types and Board

**Files:**
- Create: `src/chess/types.h`, `src/chess/board.h`, `src/chess/board.cpp`, `tests/cpp/test_board.cpp`
- Modify: `CMakeLists.txt` (add `src/chess/board.cpp` to `helpmate_core`, delete `src/placeholder.cpp`, add test file)

**Interfaces:**
- Consumes: vendored ChessMG `libsurge.h` (`Position`, `MoveList<Color>`, `Position::set`, `Position::set_position`, `play<Color>`/`undo<Color>`, `bitboard_of`, move flags).
- Produces (used by every later task):

```cpp
namespace hm {
enum class Color : uint8_t { White = 0, Black = 1 };
enum class PieceType : uint8_t { King=0, Queen=1, Rook=2, Bishop=3, Knight=4, Pawn=5 };
struct Piece { Color color; PieceType type; bool operator==(const Piece&) const = default; };
struct PlacedPiece { Piece piece; uint8_t square; };
enum class PosState : uint8_t { Open, Check, Checkmate, Stalemate };
struct ValuePair { uint8_t dtm; uint8_t count; };
constexpr uint8_t DTM_UNSET = 253, DTM_INVALID = 254, DTM_UNSOLVABLE = 255;
constexpr uint8_t DTM_MAX = 252, COUNT_SAT = 255;
inline uint8_t sat_add(unsigned a, unsigned b) { return (uint8_t)std::min(255u, a + b); }
inline int sq_file(int sq) { return sq & 7; }
inline int sq_rank(int sq) { return sq >> 3; }
std::string sq_name(int sq);                    // "e4"

struct Move {                    // flags byte uses ChessMG/surge encoding, opaque outside board.cpp
    uint8_t from, to, flags;
    bool is_capture() const; bool is_double_push() const; bool is_ep() const;
    std::optional<PieceType> promotion() const;
    std::string uci() const;                    // "e2e4", "e7e8q"
};

class Board {                    // pimpl over surge Position; copyable
public:
    Board(); Board(const Board&); Board& operator=(const Board&); ~Board();
    static std::optional<Board> from_fen(const std::string&);   // nullopt on parse error or castling rights
    static Board from_pieces(const std::vector<PlacedPiece>&, Color stm, int ep_square = -1);
    void reset(const std::vector<PlacedPiece>&, Color stm, int ep_square = -1);  // reuse allocation
    std::string fen() const;
    Color stm() const;
    int ep_square() const;                      // -1 if none
    std::vector<PlacedPiece> pieces() const;
    bool in_check() const;                      // side to move
    bool opponent_in_check() const;             // true => position illegal
    PosState state() const;                     // for side to move
    std::vector<Move> legal_moves() const;
    void make(const Move&); void unmake(const Move&);
    uint64_t perft(int depth);
};
}
```

- [ ] **Step 1: Read the vendored surge API**

Run: `sed -n '1,200p' build/_deps/chessmg-src/chessmg/libcmg/libsurge.h` (and further pages).
Note the exact names/signatures of: `Position::set(fen, pos)`, `Position::set_position(piecelist, color, castlings, epsq, pos)`, `MoveList<Color>`, `Move` accessors (`from()`, `to()`, `flags()`), the `MoveFlags` enum values (QUIET, DOUBLE_PUSH, EN_PASSANT, CAPTURE, PR_*/PC_* promotions), `play<Color>`/`undo<Color>`, `bitboard_of(Piece)`, attack/check helpers, en-passant state field. The Impl code in Step 3 must call whatever actually exists — adjust mechanically, the tests are the contract.

- [ ] **Step 2: Write the failing tests**

`tests/cpp/test_board.cpp` — the contract, including perft ground truth:
```cpp
#include <catch2/catch_test_macros.hpp>
#include "chess/board.h"
using namespace hm;

TEST_CASE("fen round trip, no castling accepted") {
    auto b = Board::from_fen("8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1");
    REQUIRE(b); CHECK(b->fen() == "8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1");
    CHECK(!Board::from_fen("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1")); // castling
    CHECK(!Board::from_fen("not a fen"));
}
TEST_CASE("perft CPW position 3 (EP-rich, castling-free)") {
    auto b = Board::from_fen("8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1");
    CHECK(b->perft(1) == 14); CHECK(b->perft(2) == 191);
    CHECK(b->perft(3) == 2812); CHECK(b->perft(4) == 43238); CHECK(b->perft(5) == 674624);
}
TEST_CASE("perft promotion-heavy position") {
    auto b = Board::from_fen("n1n5/PPPk4/8/8/8/8/4Kppp/5N1N b - - 0 1");
    CHECK(b->perft(1) == 24); CHECK(b->perft(2) == 496);
    CHECK(b->perft(3) == 9483); CHECK(b->perft(4) == 182838);
}
TEST_CASE("from_pieces / pieces round trip and state") {
    // KQvk mate: k h8, Q g7, K f6 — btm checkmate
    std::vector<PlacedPiece> pp = {
        {{Color::White, PieceType::King}, 45}, {{Color::White, PieceType::Queen}, 54},
        {{Color::Black, PieceType::King}, 63}};
    Board b = Board::from_pieces(pp, Color::Black);
    CHECK(b.state() == PosState::Checkmate);
    CHECK(b.fen() == "7k/6Q1/5K2/8/8/8/8/8 b - - 0 1");
    CHECK(b.pieces().size() == 3);
    Board w = Board::from_pieces(pp, Color::White);
    CHECK(w.opponent_in_check());               // black in check, white to move => illegal
}
TEST_CASE("stalemate detection") {
    auto b = Board::from_fen("7k/5K2/6Q1/8/8/8/8/8 b - - 0 1");  // k h8, K f7?? -> use classic: k a8, Q b6, K c7? btm
    // Classic KQ stalemate: k h8, K g6, Q g7?? is mate; use k a1, K c2, Q b3: black to move, no moves, not in check
    auto s = Board::from_fen("8/8/8/8/8/1Q6/2K5/k7 b - - 0 1");
    REQUIRE(s); CHECK(s->state() == PosState::Stalemate);
}
TEST_CASE("make/unmake restores position") {
    auto b = Board::from_fen("8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1");
    std::string before = b->fen();
    auto moves = b->legal_moves();
    REQUIRE(moves.size() == 14);
    for (auto& m : moves) { b->make(m); b->unmake(m); }
    CHECK(b->fen() == before);
}
TEST_CASE("double push sets ep square; ep move flagged") {
    auto b = Board::from_fen("8/8/8/8/1p6/8/P7/K1k5 w - - 0 1");   // a2 pawn, black b4 pawn
    auto moves = b->legal_moves();
    Move dp{};
    for (auto& m : moves) if (m.uci() == "a2a4") dp = m;
    REQUIRE(dp.uci() == "a2a4"); CHECK(dp.is_double_push());
    b->make(dp);
    CHECK(b->ep_square() == 16);                                    // a3
    bool found_ep = false;
    for (auto& m : b->legal_moves()) if (m.uci() == "b4a3" && m.is_ep()) found_ep = true;
    CHECK(found_ep);
}
TEST_CASE("promotion moves carry promotion type") {
    auto b = Board::from_fen("6k1/4P3/6K1/8/8/8/8/8 w - - 0 1");
    int promos = 0;
    for (auto& m : b->legal_moves())
        if (m.promotion()) { promos++; CHECK(m.from == 52); CHECK(m.to == 60); }
    CHECK(promos == 4);                                             // Q R B N
}
```
Note on the stalemate FEN `8/8/8/8/8/1Q6/2K5/k7 b - - 0 1`: bK a1; wQ b3 covers a2/b1/b2? b3 covers b-file (b1,b2), a2 (diagonal), a3 (rank); wK c2 covers b1,b2. a1 is not attacked. Black has no legal move → stalemate. Verified by hand; oracle re-verifies later.

- [ ] **Step 3: Run tests to verify they fail**

Run: `make test`
Expected: FAIL — `chess/board.h` not found.

- [ ] **Step 4: Implement types.h, board.h, board.cpp**

`src/chess/types.h` and `src/chess/board.h`: exactly the interface block above (split as declared; `types.h` includes `<cstdint> <optional> <string> <algorithm>`; `board.h` includes `types.h`, `<memory> <vector>`).

`src/chess/board.cpp` — the ONLY file including ChessMG headers. Implementation outline (adjust calls to the actual vendored API from Step 1):
```cpp
#include "chess/board.h"
#include "libsurge.h"     // vendored; static init contained to this TU
#include <sstream>
namespace hm {

struct Board::Impl { Position pos; Color stm; };

// --- piece mapping: hm::Piece <-> surge Piece (WHITE_PAWN=0..BLACK_KING=13) ---
static int to_surge(Piece p) {
    static const int w[6] = {WHITE_KING, WHITE_QUEEN, WHITE_ROOK, WHITE_BISHOP, WHITE_KNIGHT, WHITE_PAWN};
    static const int b[6] = {BLACK_KING, BLACK_QUEEN, BLACK_ROOK, BLACK_BISHOP, BLACK_KNIGHT, BLACK_PAWN};
    return (p.color == Color::White ? w : b)[(int)p.type];
}
static std::optional<Piece> from_surge(int sp);   // inverse, NO_PIECE -> nullopt

// --- Move flag helpers (surge MoveFlags encoding, verified in Step 1) ---
bool Move::is_capture() const   { return flags & 0b1000; }
bool Move::is_double_push() const { return flags == 0b0001; }
bool Move::is_ep() const        { return flags == 0b1010; }         // EN_PASSANT
std::optional<PieceType> Move::promotion() const {
    if ((flags & 0b0100) == 0) return std::nullopt;                 // PR_*/PC_* have bit 2 set
    switch (flags & 0b0011) { case 0: return PieceType::Knight; case 1: return PieceType::Bishop;
                              case 2: return PieceType::Rook;   default: return PieceType::Queen; }
}
std::string Move::uci() const { /* sq_name(from)+sq_name(to)+ optional "nbrq" letter */ }

Board::Board() : impl_(new Impl{}) { impl_->stm = Color::White; }
// copy ctor/assign deep-copy impl_; dtor default.

std::optional<Board> Board::from_fen(const std::string& fen) {
    // reject castling: field 3 of FEN must be "-"
    std::istringstream ss(fen); std::string board_s, stm_s, cast_s, ep_s;
    if (!(ss >> board_s >> stm_s >> cast_s >> ep_s)) return std::nullopt;
    if (cast_s != "-") return std::nullopt;
    Board b; Position::set(fen, b.impl_->pos);          // surge FEN parser
    b.impl_->stm = (stm_s == "w") ? Color::White : Color::Black;
    if (b.pieces().empty()) return std::nullopt;        // parse failure heuristic; also validate 1 K + 1 k
    return b;
}
void Board::reset(const std::vector<PlacedPiece>& pp, Color stm, int ep) {
    std::vector<std::pair<int,int>> pl;                 // (surge piece, square) — actual pair types per Step 1
    for (auto& p : pp) pl.push_back({to_surge(p.piece), p.square});
    Position::set_position(pl, stm == Color::White ? WHITE : BLACK, "-",
                           ep < 0 ? NO_SQUARE : (Square)ep, impl_->pos);
    impl_->stm = stm;
}
// from_pieces = default-construct + reset.

std::vector<Move> Board::legal_moves() const {
    std::vector<Move> out;
    auto conv = [&](auto& list){ for (auto m : list) out.push_back({(uint8_t)m.from(), (uint8_t)m.to(), (uint8_t)m.flags()}); };
    if (impl_->stm == Color::White) { MoveList<WHITE> l(impl_->pos); conv(l); }
    else                            { MoveList<BLACK> l(impl_->pos); conv(l); }
    return out;
}
void Board::make(const Move& m) {
    ::Move sm(Square(m.from), Square(m.to), MoveFlags(m.flags));
    if (impl_->stm == Color::White) impl_->pos.play<WHITE>(sm); else impl_->pos.play<BLACK>(sm);
    impl_->stm = impl_->stm == Color::White ? Color::Black : Color::White;
}
// unmake mirrors with undo<Color> (color = the side that made the move).

bool Board::in_check() const  { /* attackers of ~stm on stm's king square != 0, via surge attack helpers */ }
bool Board::opponent_in_check() const { /* attackers of stm on opponent king square != 0 */ }
PosState Board::state() const {
    bool any = !legal_moves().empty(); bool chk = in_check();
    if (any) return chk ? PosState::Check : PosState::Open;
    return chk ? PosState::Checkmate : PosState::Stalemate;
}
std::vector<PlacedPiece> Board::pieces() const { /* scan 64 squares via pos.at(sq) or board[] accessor */ }
int Board::ep_square() const { /* surge history/ep field; NO_SQUARE -> -1 */ }
std::string Board::fen() const { /* surge pos.fen(); normalize stm/ep fields if needed to match tests */ }
uint64_t Board::perft(int depth) { /* recursive make/unmake over legal_moves, depth 0 -> 1 */ }
}
```
Where a comment says "per Step 1", use the real vendored signature. Implement `perft` on top of our own `legal_moves`/`make`/`unmake` (NOT surge's built-in perft) — that is the point of the test: it validates the adapter.

- [ ] **Step 5: Wire into CMake**

In `CMakeLists.txt`: `helpmate_core` sources → `src/chess/board.cpp`; remove `src/placeholder.cpp` (delete the file); `helpmate_tests` sources → add `tests/cpp/test_board.cpp`.

- [ ] **Step 6: Run tests until green**

Run: `make test`
Expected: all `test_board` cases PASS. Perft mismatches mean adapter bugs (flag decoding, EP, stm bookkeeping) — debug with `perft_moves`-style per-move breakdown against the failing depth.

- [ ] **Step 7: Commit**

```bash
git add src/chess tests/cpp/test_board.cpp CMakeLists.txt
git rm src/placeholder.cpp
git commit -m "feat: Board adapter over ChessMG with perft-verified movegen"
```

---

### Task 3: SAN formatter

**Files:**
- Create: `src/chess/san.h`, `src/chess/san.cpp`, `tests/cpp/test_san.cpp`
- Modify: `CMakeLists.txt` (add sources)

**Interfaces:**
- Consumes: `Board`, `Move` (Task 2).
- Produces: `std::string hm::san(Board& b, const Move& m);` — SAN for a legal move of `b`, with `+`/`#` suffix (board is restored before returning).

- [ ] **Step 1: Write the failing tests**

`tests/cpp/test_san.cpp`:
```cpp
#include <catch2/catch_test_macros.hpp>
#include "chess/board.h"
#include "chess/san.h"
using namespace hm;
static std::string san_of(const std::string& fen, const std::string& uci) {
    auto b = Board::from_fen(fen); REQUIRE(b);
    for (auto& m : b->legal_moves()) if (m.uci() == uci) return san(*b, m);
    FAIL("move not legal"); return "";
}
TEST_CASE("san basics") {
    CHECK(san_of("7k/8/5K2/8/8/8/8/6Q1 w - - 0 1", "g1g7") == "Qg7#");
    CHECK(san_of("6k1/4P3/6K1/8/8/8/8/8 w - - 0 1", "e7e8q") == "e8=Q#");
    CHECK(san_of("6k1/4P3/6K1/8/8/8/8/8 w - - 0 1", "e7e8n") == "e8=N");
    CHECK(san_of("8/8/8/8/1p6/8/P7/K1k5 w - - 0 1", "a2a4") == "a4");
    // pawn capture with file prefix:
    CHECK(san_of("8/8/8/3p4/2P5/8/8/K1k5 w - - 0 1", "c4d5") == "cxd5");
    // disambiguation: two rooks on same rank
    CHECK(san_of("8/8/8/8/R3K2R/8/8/k7 w - - 0 1", "a4d4") == "Rad4");
}
```
(For `R3K2R` FEN: rooks a4 + h4, both can reach d4? h4→d4 passes e4 = King — blocked, so NO disambiguation needed → expected `Rd4`. Fix the test: use `8/8/8/8/R6R/8/8/k3K3 w - - 0 1`, rooks a4 h4, kings a1/e1; both rooks reach d4 → `Rad4`.)

- [ ] **Step 2: Run to verify failure** — `make test`, expect missing `san.h`.

- [ ] **Step 3: Implement**

`src/chess/san.cpp`: piece letter (`""` for pawn, else `KQRBN`); for non-pawns, disambiguate by scanning `b.legal_moves()` for other moves of same piece type to same `to` (add file, else rank, else both); `x` if `m.is_capture()` (pawn captures prefixed with from-file); destination `sq_name(m.to)`; `=X` for promotion; then `b.make(m)`, append `#` if `state()==Checkmate`, `+` if `Check`, `b.unmake(m)`. Piece type at `from` comes from `b.pieces()`.

- [ ] **Step 4: Run tests** — `make test`, expect PASS.

- [ ] **Step 5: Commit** — `git add src/chess/san.* tests/cpp/test_san.cpp CMakeLists.txt && git commit -m "feat: SAN formatter"`

---

### Task 4: Material model and slice DAG

**Files:**
- Create: `src/indexing/material.h`, `src/indexing/material.cpp`, `tests/cpp/test_material.cpp`
- Modify: `CMakeLists.txt`

**Interfaces:**
- Consumes: `PieceType`, `Color`, `PlacedPiece` (Task 2).
- Produces:

```cpp
namespace hm {
struct Material {
    std::array<uint8_t, 6> white{}, black{};        // counts indexed by PieceType
    static std::optional<Material> parse(const std::string&);  // "KBkqrbp" or "KBvkqrbp"
    static Material of(const std::vector<PlacedPiece>&);
    std::string name() const;                       // canonical "KBvkqrbp"
    bool operator==(const Material&) const = default;
    bool has_pawns() const; int total() const; int pawn_count() const;
    std::vector<Material> successors() const;       // capture / promotion / promotion-capture results
    static std::vector<Material> closure_topo(const Material& root); // build order, root last
};
}
```

- [ ] **Step 1: Write the failing tests**

`tests/cpp/test_material.cpp`:
```cpp
#include <catch2/catch_test_macros.hpp>
#include "indexing/material.h"
#include <set>
using namespace hm;
TEST_CASE("parse and canonical name") {
    auto m = Material::parse("KBkqrbp"); REQUIRE(m);
    CHECK(m->name() == "KBvkqrbp");
    CHECK(Material::parse("KQvk")->name() == "KQvk");
    CHECK(Material::parse("KPpk"));                    // order-insensitive within a color
    CHECK(!Material::parse("KQ"));                     // missing black king
    CHECK(!Material::parse("KKk"));                    // two white kings
    CHECK(Material::parse("KQvk")->total() == 3);
    CHECK(!Material::parse("KQvk")->has_pawns());
    CHECK(Material::parse("KPvkp")->pawn_count() == 2);
}
TEST_CASE("successors of KPvk") {
    auto m = *Material::parse("KPvk");
    std::set<std::string> names;
    for (auto& s : m.successors()) names.insert(s.name());
    CHECK(names == std::set<std::string>{"Kvk", "KQvk", "KRvk", "KBvk", "KNvk"});
}
TEST_CASE("closure is topologically ordered") {
    auto order = Material::closure_topo(*Material::parse("KQvkp"));
    CHECK(order.back().name() == "KQvkp");
    auto pos_of = [&](const std::string& n) {
        for (size_t i = 0; i < order.size(); ++i) if (order[i].name() == n) return (int)i;
        return -1; };
    for (auto& m : order)                              // property: successors appear strictly earlier
        for (auto& s : m.successors()) {
            INFO(m.name() << " -> " << s.name());
            CHECK(pos_of(s.name()) >= 0);
            CHECK(pos_of(s.name()) < pos_of(m.name()));
        }
}
TEST_CASE("closure of KPvk exact") {
    auto order = Material::closure_topo(*Material::parse("KPvk"));
    REQUIRE(order.size() == 6);
    CHECK(order.front().name() == "Kvk");
    CHECK(order.back().name() == "KPvk");
}
```

- [ ] **Step 2: Run to verify failure** — `make test`.

- [ ] **Step 3: Implement**

`material.cpp` essentials:
```cpp
static const char WLET[7] = "KQRBNP";
std::optional<Material> Material::parse(const std::string& s) {
    Material m;
    for (char c : s) {
        if (c == 'v') continue;
        const char* p = strchr(WLET, toupper(c));
        if (!p || !*p) return std::nullopt;
        (isupper(c) ? m.white : m.black)[p - WLET]++;
    }
    if (m.white[0] != 1 || m.black[0] != 1) return std::nullopt;
    return m;
}
std::string Material::name() const {
    std::string out;
    for (int t = 0; t < 6; ++t) out.append(white[t], WLET[t]);
    out += 'v';
    for (int t = 0; t < 6; ++t) out.append(black[t], (char)tolower(WLET[t]));
    return out;
}
std::vector<Material> Material::successors() const {
    std::vector<Material> out;
    auto add = [&](const Material& m) { if (std::find(out.begin(), out.end(), m) == out.end()) out.push_back(m); };
    for (int t = 1; t < 6; ++t) {                     // captures: either color loses a non-king
        if (white[t]) { Material m = *this; m.white[t]--; add(m); }
        if (black[t]) { Material m = *this; m.black[t]--; add(m); }
    }
    for (int p = 1; p <= 4; ++p) {                    // promotions P -> Q/R/B/N
        if (white[5]) { Material m = *this; m.white[5]--; m.white[p]++; add(m); }
        if (black[5]) { Material m = *this; m.black[5]--; m.black[p]++; add(m); }
        for (int t = 1; t < 6; ++t) {                 // promotion-captures
            if (white[5] && black[t]) { Material m = *this; m.white[5]--; m.white[p]++; m.black[t]--; add(m); }
            if (black[5] && white[t]) { Material m = *this; m.black[5]--; m.black[p]++; m.white[t]--; add(m); }
        }
    }
    return out;
}
std::vector<Material> Material::closure_topo(const Material& root) {
    std::vector<Material> all{root};                  // BFS closure
    for (size_t i = 0; i < all.size(); ++i)
        for (auto& s : all[i].successors())
            if (std::find(all.begin(), all.end(), s) == all.end()) all.push_back(s);
    std::sort(all.begin(), all.end(), [](const Material& a, const Material& b) {
        return std::tuple(a.total(), a.pawn_count(), a.name())
             < std::tuple(b.total(), b.pawn_count(), b.name()); });
    return all;
}
```
Why the sort is a valid topological order: a capture lowers `total`; a promotion keeps `total` and lowers `pawn_count`; a promotion-capture lowers both — every successor is strictly smaller in `(total, pawn_count)` lexicographic order.

- [ ] **Step 4: Run tests** — `make test`, expect PASS.
- [ ] **Step 5: Commit** — `git add src/indexing tests/cpp/test_material.cpp CMakeLists.txt && git commit -m "feat: material model with capture/promotion closure"`

---

### Task 5: Symmetry transforms and KK tables

**Files:**
- Create: `src/indexing/kk.h`, `src/indexing/kk.cpp`, `tests/cpp/test_kk.cpp`
- Modify: `CMakeLists.txt`

**Interfaces:**
- Produces:

```cpp
namespace hm {
// t in [0,8): bit0 = mirror files (a<->h), bit1 = mirror ranks, bit2 = transpose (a1-h8 diag).
// Applied in that order. With pawns only t in {0,1} is allowed.
inline int transform_sq(int sq, int t) {
    if (t & 1) sq ^= 7;
    if (t & 2) sq ^= 56;
    if (t & 4) sq = ((sq & 7) << 3) | (sq >> 3);
    return sq;
}
struct KKTable {
    int size = 0;
    std::array<int32_t, 4096> index_of;               // wk*64+bk -> kk index, -1 if outside canonical region/illegal
    std::vector<std::pair<uint8_t, uint8_t>> squares_of;
    static const KKTable& with_pawns();               // wK on files a-d; size 1806
    static const KKTable& pawnless();                 // wK in a1-d1-d4 triangle; size 462
};
bool kings_adjacent(int a, int b);
}
```

- [ ] **Step 1: Write the failing tests**

`tests/cpp/test_kk.cpp`:
```cpp
#include <catch2/catch_test_macros.hpp>
#include "indexing/kk.h"
#include "chess/types.h"
using namespace hm;
TEST_CASE("transform_sq basics and bijectivity") {
    CHECK(transform_sq(0, 0) == 0);
    CHECK(transform_sq(0, 1) == 7);      // a1 -> h1
    CHECK(transform_sq(0, 2) == 56);     // a1 -> a8
    CHECK(transform_sq(1, 4) == 8);      // b1 -> a2 (transpose)
    for (int t = 0; t < 8; ++t) {
        bool seen[64] = {};
        for (int s = 0; s < 64; ++s) { int x = transform_sq(s, t); REQUIRE(!seen[x]); seen[x] = true; }
    }
}
TEST_CASE("kk table sizes are the standard values") {
    CHECK(KKTable::with_pawns().size == 1806);
    CHECK(KKTable::pawnless().size == 462);
}
TEST_CASE("kk tables are consistent bijections") {
    for (auto* tbl : {&KKTable::with_pawns(), &KKTable::pawnless()}) {
        for (int i = 0; i < tbl->size; ++i) {
            auto [wk, bk] = tbl->squares_of[i];
            CHECK(tbl->index_of[wk * 64 + bk] == i);
            CHECK(!kings_adjacent(wk, bk)); CHECK(wk != bk);
        }
    }
}
TEST_CASE("every king square reaches the canonical region") {
    for (int wk = 0; wk < 64; ++wk) {                 // pawns: exactly one of {id, mirror}
        int hits = 0;
        for (int t = 0; t < 2; ++t) if (sq_file(transform_sq(wk, t)) < 4) hits++;
        CHECK(hits == 1);
    }
    auto in_tri = [](int s) { return sq_file(s) < 4 && sq_rank(s) <= sq_file(s); };
    for (int wk = 0; wk < 64; ++wk) {                 // pawnless: at least one of 8
        int hits = 0;
        for (int t = 0; t < 8; ++t) if (in_tri(transform_sq(wk, t))) hits++;
        CHECK(hits >= 1);
    }
}
```

- [ ] **Step 2: Run to verify failure** — `make test`.

- [ ] **Step 3: Implement**

`kk.cpp`: `kings_adjacent(a,b)` = both |file delta| ≤ 1 and |rank delta| ≤ 1, a ≠ b. Tables built once via function-local static:
```cpp
static KKTable build(bool pawns) {
    KKTable t; t.index_of.fill(-1);
    for (int wk = 0; wk < 64; ++wk) {
        bool ok = pawns ? sq_file(wk) < 4
                        : (sq_file(wk) < 4 && sq_rank(wk) <= sq_file(wk));
        if (!ok) continue;
        for (int bk = 0; bk < 64; ++bk) {
            if (bk == wk || kings_adjacent(wk, bk)) continue;
            t.index_of[wk * 64 + bk] = t.size++;
            t.squares_of.push_back({(uint8_t)wk, (uint8_t)bk});
        }
    }
    return t;
}
```

- [ ] **Step 4: Run tests** — `make test`, expect PASS (1806/462 confirm the construction).
- [ ] **Step 5: Commit** — `git add src/indexing/kk.* tests/cpp/test_kk.cpp CMakeLists.txt && git commit -m "feat: symmetry transforms and KK index tables"`

---

### Task 6: Slice indexing — encode/decode

**Files:**
- Create: `src/indexing/slice_index.h`, `src/indexing/slice_index.cpp`, `tests/cpp/test_slice_index.cpp`
- Modify: `CMakeLists.txt`

**Interfaces:**
- Consumes: `Material` (T4), `KKTable`/`transform_sq` (T5), `PlacedPiece` (T2).
- Produces:

```cpp
namespace hm {
class SliceIndex {
public:
    explicit SliceIndex(const Material&);
    uint64_t size() const;                            // cells per side-to-move plane
    // canonical index = min over allowed transforms; identical pieces sorted by transformed square.
    // nullopt if pieces don't match the material, kings adjacent/equal, or a pawn off ranks 2-7.
    std::optional<uint64_t> encode(const std::vector<PlacedPiece>&) const;
    // false if idx >= size() or decoded pieces overlap; kings come from the KK table.
    bool decode(uint64_t idx, std::vector<PlacedPiece>& out) const;
    int num_transforms() const;                       // 2 with pawns, 8 without
};
}
```

- [ ] **Step 1: Write the failing tests**

`tests/cpp/test_slice_index.cpp`:
```cpp
#include <catch2/catch_test_macros.hpp>
#include "indexing/slice_index.h"
#include "indexing/material.h"
#include <random>
#include <tuple>
using namespace hm;
TEST_CASE("plane sizes") {
    CHECK(SliceIndex(*Material::parse("Kvk")).size()   == 462);
    CHECK(SliceIndex(*Material::parse("KQvk")).size()  == 462ull * 64);
    CHECK(SliceIndex(*Material::parse("KPvk")).size()  == 1806ull * 48);
    CHECK(SliceIndex(*Material::parse("KQvkq")).size() == 462ull * 64 * 64);
    CHECK(SliceIndex(*Material::parse("KPvkp")).size() == 1806ull * 48 * 48);
}
static std::vector<PlacedPiece> transform_pos(const std::vector<PlacedPiece>& pp, int t) {
    auto out = pp; for (auto& p : out) p.square = (uint8_t)transform_sq(p.square, t); return out;
}
TEST_CASE("all symmetry images share one canonical index (pawnless)") {
    SliceIndex idx(*Material::parse("KQvkr"));
    std::vector<PlacedPiece> pp = {
        {{Color::White, PieceType::King}, 12}, {{Color::White, PieceType::Queen}, 33},
        {{Color::Black, PieceType::King}, 60}, {{Color::Black, PieceType::Rook}, 7}};
    auto base = idx.encode(pp); REQUIRE(base);
    for (int t = 1; t < 8; ++t) CHECK(idx.encode(transform_pos(pp, t)) == base);
}
TEST_CASE("mirror image shares canonical index (pawns)") {
    SliceIndex idx(*Material::parse("KPvkp"));
    std::vector<PlacedPiece> pp = {
        {{Color::White, PieceType::King}, 4},  {{Color::White, PieceType::Pawn}, 28},
        {{Color::Black, PieceType::King}, 20}, {{Color::Black, PieceType::Pawn}, 35}};
    auto base = idx.encode(pp); REQUIRE(base);
    CHECK(idx.encode(transform_pos(pp, 1)) == base);
}
TEST_CASE("decode/encode round trip over random cells") {
    for (auto name : {"KQvkr", "KPvkp", "KQQvk"}) {
        SliceIndex idx(*Material::parse(name));
        std::mt19937_64 rng(42);
        std::vector<PlacedPiece> pp;
        int checked = 0;
        while (checked < 2000) {
            uint64_t c = rng() % idx.size();
            if (!idx.decode(c, pp)) continue;         // overlapping cell
            auto e = idx.encode(pp);
            REQUIRE(e);
            CHECK(*e <= c);                           // canonical is minimal
            checked++;
        }
    }
}
TEST_CASE("identical pieces: swapped order encodes identically") {
    SliceIndex idx(*Material::parse("KQQvk"));
    std::vector<PlacedPiece> a = {
        {{Color::White, PieceType::King}, 0}, {{Color::White, PieceType::Queen}, 10},
        {{Color::White, PieceType::Queen}, 20}, {{Color::Black, PieceType::King}, 63}};
    auto b = a; std::swap(b[1], b[2]);
    CHECK(idx.encode(a) == idx.encode(b));
}
TEST_CASE("encode rejects garbage") {
    SliceIndex idx(*Material::parse("KQvk"));
    std::vector<PlacedPiece> wrong = {
        {{Color::White, PieceType::King}, 0}, {{Color::Black, PieceType::King}, 63}};
    CHECK(!idx.encode(wrong));                        // material mismatch (missing Q)
    std::vector<PlacedPiece> adj = {
        {{Color::White, PieceType::King}, 0}, {{Color::White, PieceType::Queen}, 30},
        {{Color::Black, PieceType::King}, 1}};
    CHECK(!idx.encode(adj));                          // adjacent kings
}
```

- [ ] **Step 2: Run to verify failure** — `make test`.

- [ ] **Step 3: Implement**

`slice_index.cpp` core:
```cpp
struct Slot { Piece piece; int radix; };              // radix 64; pawns 48 (digit = sq-8)

SliceIndex::SliceIndex(const Material& m) : mat_(m) {
    pawns_ = m.has_pawns();
    kk_ = pawns_ ? &KKTable::with_pawns() : &KKTable::pawnless();
    for (int color = 0; color < 2; ++color)           // fixed order: white Q,R,B,N,P then black q,r,b,n,p
        for (int t = 1; t < 6; ++t) {
            const auto& cnt = color == 0 ? m.white : m.black;
            for (int k = 0; k < cnt[t]; ++k)
                slots_.push_back({{(Color)color, (PieceType)t}, t == 5 ? 48 : 64});
        }
    size_ = kk_->size;
    for (auto& s : slots_) size_ *= (uint64_t)s.radix;
}

std::optional<uint64_t> SliceIndex::encode(const std::vector<PlacedPiece>& pp) const {
    if (!(Material::of(pp) == mat_)) return std::nullopt;
    int wk = -1, bk = -1;
    for (auto& p : pp) if (p.piece.type == PieceType::King)
        (p.piece.color == Color::White ? wk : bk) = p.square;
    uint64_t best = UINT64_MAX;
    for (int t = 0; t < num_transforms(); ++t) {
        int kk = kk_->index_of[transform_sq(wk, t) * 64 + transform_sq(bk, t)];
        if (kk < 0) continue;
        uint64_t idx = (uint64_t)kk; bool ok = true;
        size_t i = 0;
        while (i < slots_.size() && ok) {
            size_t j = i;                             // run of identical slots
            while (j < slots_.size() && slots_[j].piece == slots_[i].piece) j++;
            std::vector<int> sqs;
            for (auto& p : pp)
                if (p.piece == slots_[i].piece) sqs.push_back(transform_sq(p.square, t));
            std::sort(sqs.begin(), sqs.end());
            for (size_t k = i; k < j; ++k) {
                int digit = sqs[k - i] - (slots_[k].radix == 48 ? 8 : 0);
                if (digit < 0 || digit >= slots_[k].radix) { ok = false; break; }
                idx = idx * slots_[k].radix + (uint64_t)digit;
            }
            i = j;
        }
        if (ok) best = std::min(best, idx);
    }
    if (best == UINT64_MAX) return std::nullopt;      // e.g. kings adjacent
    return best;
}

bool SliceIndex::decode(uint64_t idx, std::vector<PlacedPiece>& out) const {
    if (idx >= size_) return false;
    out.clear();
    uint64_t rest = idx;
    std::vector<int> dg(slots_.size());
    for (int i = (int)slots_.size() - 1; i >= 0; --i) { dg[i] = rest % slots_[i].radix; rest /= slots_[i].radix; }
    auto [wk, bk] = kk_->squares_of[rest];            // remaining = kk index
    uint64_t occ = (1ull << wk) | (1ull << bk);
    out.push_back({{Color::White, PieceType::King}, wk});
    out.push_back({{Color::Black, PieceType::King}, bk});
    for (size_t i = 0; i < slots_.size(); ++i) {
        int sq = dg[i] + (slots_[i].radix == 48 ? 8 : 0);
        if (occ & (1ull << sq)) return false;         // overlap -> invalid cell
        occ |= 1ull << sq;
        out.push_back({slots_[i].piece, (uint8_t)sq});
    }
    return true;
}
```
Invariant checked by the round-trip test: `encode(decode(c)) <= c`, equality exactly on canonical cells. Non-canonical cells (symmetry duplicates, unsorted identical pieces) get `DTM_INVALID` in Task 9's init pass.

- [ ] **Step 4: Run tests** — `make test`, expect PASS.
- [ ] **Step 5: Commit** — `git add src/indexing/slice_index.* tests/cpp/test_slice_index.cpp CMakeLists.txt && git commit -m "feat: slice indexing with symmetry canonicalization"`

---

### Task 7: Table file format

**Files:**
- Create: `src/format/table_file.h`, `src/format/table_file.cpp`, `tests/cpp/test_table_file.cpp`
- Modify: `CMakeLists.txt`

**Interfaces:**
- Consumes: `Material` (T4), `ValuePair` (T2).
- Produces:

```cpp
namespace hm {
#pragma pack(push, 1)
struct TableHeader {
    char magic[4];            // "HM8P"
    uint32_t version;         // 1
    uint8_t encoding;         // 1 = raw byte planes
    uint8_t symmetry;         // 0 = with pawns (2 transforms), 1 = pawnless (8)
    char material[26];        // canonical name, NUL padded
    uint64_t plane_size;
    uint8_t max_dtm;          // DTM_UNSOLVABLE if no cell solvable
    uint8_t reserved[15];
    uint32_t json_len;        // metadata JSON directly after header
};                            // static_assert(sizeof(TableHeader) == 64)
#pragma pack(pop)
// payload after JSON: 4 planes of plane_size bytes each: dtm_wtm, dtm_btm, cnt_wtm, cnt_btm

struct TableWriter {          // writes "<path>.tmp" then atomic-renames to path
    static void write(const std::string& path, const Material&, uint64_t plane_size, uint8_t max_dtm,
                      const std::string& meta_json,
                      const uint8_t* dtm_w, const uint8_t* dtm_b,
                      const uint8_t* cnt_w, const uint8_t* cnt_b);
};
class TableReader {           // mmap; movable, not copyable
public:
    static std::optional<TableReader> open(const std::string& path);
    ValuePair get(Color stm, uint64_t cell) const;
    uint64_t plane_size() const; uint8_t max_dtm() const;
    std::string material_name() const; std::string meta_json() const;
};
}
```

- [ ] **Step 1: Write the failing tests**

`tests/cpp/test_table_file.cpp`:
```cpp
#include <catch2/catch_test_macros.hpp>
#include "format/table_file.h"
#include "indexing/material.h"
#include <filesystem>
using namespace hm;
TEST_CASE("header is 64 bytes") { CHECK(sizeof(TableHeader) == 64); }
TEST_CASE("write/read round trip") {
    auto dir = std::filesystem::temp_directory_path() / "hm_test_tables";
    std::filesystem::create_directories(dir);
    auto path = (dir / "KQvk.hm").string();
    const uint64_t n = 1000;
    std::vector<uint8_t> dw(n), db(n), cw(n), cb(n);
    for (uint64_t i = 0; i < n; ++i) { dw[i] = i % 250; db[i] = (i * 7) % 250; cw[i] = i % 3; cb[i] = 1; }
    TableWriter::write(path, *Material::parse("KQvk"), n, 42, "{\"hello\":1}",
                       dw.data(), db.data(), cw.data(), cb.data());
    auto r = TableReader::open(path);
    REQUIRE(r);
    CHECK(r->plane_size() == n); CHECK(r->max_dtm() == 42);
    CHECK(r->material_name() == "KQvk");
    CHECK(r->meta_json() == "{\"hello\":1}");
    for (uint64_t i : {0ull, 1ull, 500ull, 999ull}) {
        CHECK(r->get(Color::White, i).dtm == dw[i]); CHECK(r->get(Color::White, i).count == cw[i]);
        CHECK(r->get(Color::Black, i).dtm == db[i]); CHECK(r->get(Color::Black, i).count == cb[i]);
    }
    CHECK(!TableReader::open((dir / "missing.hm").string()));
}
```

- [ ] **Step 2: Run to verify failure** — `make test`.

- [ ] **Step 3: Implement**

`table_file.cpp`: writer streams header + JSON + four planes to `path + ".tmp"` with `std::ofstream`, then `std::filesystem::rename`. Reader: POSIX `open`/`fstat`/`mmap(PROT_READ, MAP_SHARED)`; validates magic/version/encoding and `filesize == 64 + json_len + 4*plane_size`:
```cpp
ValuePair TableReader::get(Color stm, uint64_t cell) const {
    const uint8_t* pay = base_ + 64 + json_len_;
    uint64_t o = (stm == Color::Black ? ps_ : 0) + cell;
    return { pay[o], pay[2 * ps_ + o] };
}
```
Destructor `munmap`s; move constructor nulls the source.

- [ ] **Step 4: Run tests** — `make test`, expect PASS.
- [ ] **Step 5: Commit** — `git add src/format tests/cpp/test_table_file.cpp CMakeLists.txt && git commit -m "feat: HM8P table file format with mmap reader"`

---

### Task 8: Cooperative oracle solver

**Files:**
- Create: `src/generator/oracle.h`, `src/generator/oracle.cpp`, `tests/cpp/test_oracle.cpp`
- Modify: `CMakeLists.txt`

**Interfaces:**
- Consumes: `Board` (T2) only — deliberately independent of indexing/tables so it can cross-check them.
- Produces:

```cpp
namespace hm {
struct OracleResult { int dtm; int count; };          // count saturates at 255
// Smallest ply distance to "Black is checkmated" with both sides cooperating,
// searching real game rules via Board (incl. EP, promotions, captures).
// nullopt if no mate within max_plies.
std::optional<OracleResult> oracle_solve(Board b, int max_plies);
}
```

- [ ] **Step 1: Write the failing tests (the hand-verified golden set)**

`tests/cpp/test_oracle.cpp`:
```cpp
#include <catch2/catch_test_macros.hpp>
#include "generator/oracle.h"
using namespace hm;
static OracleResult solve(const std::string& fen, int maxp = 12) {
    auto b = Board::from_fen(fen); REQUIRE(b);
    auto r = oracle_solve(*b, maxp); REQUIRE(r); return *r;
}
// G0: k h8, Q g7 (guarded by K f6) — Black already checkmated.
TEST_CASE("golden dtm 0") {
    auto r = solve("7k/6Q1/5K2/8/8/8/8/8 b - - 0 1");
    CHECK(r.dtm == 0); CHECK(r.count == 1);
}
// G1: same but Q on g1, wtm — 1. Qg7# is the only mate.
TEST_CASE("golden dtm 1, unique") {
    auto r = solve("7k/8/5K2/8/8/8/8/6Q1 w - - 0 1");
    CHECK(r.dtm == 1); CHECK(r.count == 1);
}
// G2: bK h7 — 1... Kh8 (g7/g8 are illegal: Q g1 sweeps the g-file; Kh6 leads deeper) 2. Qg7#.
TEST_CASE("golden dtm 2, unique") {
    auto r = solve("8/7k/5K2/8/8/8/8/6Q1 b - - 0 1");
    CHECK(r.dtm == 2); CHECK(r.count == 1);
}
// G3: Q a1, wtm — 1. Qg1 Kh8 2. Qg7#. No mate in 1 (Qa1-g7 is blocked by wK f6).
TEST_CASE("golden dtm 3") {
    CHECK(solve("8/7k/5K2/8/8/8/8/Q7 w - - 0 1").dtm == 3);
}
// G4 promotion: wK g6, wP e7, bK g8, wtm — 1. e8=Q# and 1. e8=R# both mate: count 2.
TEST_CASE("golden promotion mate, count 2 (Q and R promotion)") {
    auto r = solve("6k1/4P3/6K1/8/8/8/8/8 w - - 0 1");
    CHECK(r.dtm == 1); CHECK(r.count == 2);
}
TEST_CASE("unsolvable within horizon") {
    auto b = Board::from_fen("8/8/8/8/8/4k3/8/4K3 w - - 0 1");   // Kvk
    CHECK(!oracle_solve(*b, 10));
}
TEST_CASE("stalemate has no continuation") {
    auto b = Board::from_fen("8/8/8/8/8/1Q6/2K5/k7 b - - 0 1");
    CHECK(!oracle_solve(*b, 8));
}
```
If any golden value disagrees with the implementation, apply the Global Constraints rule: re-verify on a physical/GUI board before touching the test.

- [ ] **Step 2: Run to verify failure** — `make test`.

- [ ] **Step 3: Implement**

`oracle.cpp` — iterative deepening with exact-length path counting and memoization:
```cpp
#include "generator/oracle.h"
#include <unordered_map>
namespace hm {
namespace {
struct Ctx { std::unordered_map<uint64_t, int> memo; };   // key: zobrist ^ plies_left
// Number of move sequences of length EXACTLY plies_left that end in Black checkmated
// (saturating at 255). For the minimal target this equals the optimal-line count:
// any successor s of a dtm-d position has dtm(s) >= d-1, so exact-length lines can
// only pass through optimal successors.
int paths(Board& b, int plies_left, Ctx& c) {
    if (plies_left == 0)
        return (b.stm() == Color::Black && b.state() == PosState::Checkmate) ? 1 : 0;
    uint64_t key = b.hash() * 1000003ull + (uint64_t)plies_left;
    if (auto it = c.memo.find(key); it != c.memo.end()) return it->second;
    unsigned total = 0;
    for (const Move& m : b.legal_moves()) {
        b.make(m);
        total = std::min(255u, total + (unsigned)paths(b, plies_left - 1, c));
        b.unmake(m);
    }
    c.memo.emplace(key, (int)total);
    return (int)total;
}
}
std::optional<OracleResult> oracle_solve(Board b, int max_plies) {
    Ctx c;
    int start = (b.stm() == Color::Black) ? 0 : 1;            // parity: btm even, wtm odd
    for (int target = start; target <= max_plies; target += 2) {
        int n = paths(b, target, c);
        if (n > 0) return OracleResult{target, n};
    }
    return std::nullopt;
}
}
```
This requires one addition to `Board` (extend Task 2's files here): `uint64_t Board::hash() const;` exposing surge's incrementally-updated zobrist key (covers side to move and EP state). Add a regression test in `test_board.cpp`: hash changes after `make`, restored after `unmake`.

- [ ] **Step 4: Run tests** — `make test`, expect PASS.
- [ ] **Step 5: Commit** — `git add src/generator tests/cpp/test_oracle.cpp src/chess CMakeLists.txt && git commit -m "feat: cooperative IDDFS oracle with exact-length line counting"`

---

### Task 9: Generator — init pass

**Files:**
- Create: `src/generator/generator.h`, `src/generator/generator.cpp`, `tests/cpp/test_generator_init.cpp`
- Modify: `CMakeLists.txt`

**Interfaces:**
- Consumes: `Board`, `SliceIndex`, `Material`, sentinels.
- Produces (grows in Tasks 10/12/13; declared now):

```cpp
namespace hm {
struct GenOptions { std::string tables_dir = "tables"; int threads = 1; };
// Builds the whole closure (missing slices only), root last. Returns paths of written files.
std::vector<std::string> generate(const Material& root, const GenOptions& = {});

class SliceGen {                                      // exposed for tests
public:
    SliceGen(const Material&, const GenOptions&);
    void init_pass();
    bool scan_pass(int d);                            // Task 10
    void run_all_passes();                            // Task 10: scan until fixed point; sets max_dtm_
    void count_sweep();                               // Task 12
    void finalize_and_write();                        // Task 10 (stats extended in Task 13)
    // test accessors:
    const std::vector<uint8_t>& dtm(Color stm) const;
    const std::vector<uint8_t>& cnt(Color stm) const;
    const SliceIndex& index() const;
    int max_dtm() const;
};
}
```

- [ ] **Step 1: Write the failing tests**

`tests/cpp/test_generator_init.cpp`:
```cpp
#include <catch2/catch_test_macros.hpp>
#include "generator/generator.h"
#include "chess/board.h"
using namespace hm;
static uint64_t cell_of(SliceGen& g, const std::string& fen) {
    auto b = Board::from_fen(fen); REQUIRE(b);
    auto e = g.index().encode(b->pieces()); REQUIRE(e); return *e;
}
TEST_CASE("init pass classifies KQvk") {
    SliceGen g(*Material::parse("KQvk"), {});
    g.init_pass();
    // G0 mate cell is dtm 0 on the btm plane
    uint64_t mate = cell_of(g, "7k/6Q1/5K2/8/8/8/8/8 b - - 0 1");
    CHECK(g.dtm(Color::Black)[mate] == 0);
    // same placement, wtm: Black in check but White to move -> INVALID
    CHECK(g.dtm(Color::White)[mate] == DTM_INVALID);
    // an open position is UNSET on both planes
    uint64_t open = cell_of(g, "8/7k/5K2/8/8/8/8/Q7 w - - 0 1");
    CHECK(g.dtm(Color::White)[open] == DTM_UNSET);
    CHECK(g.dtm(Color::Black)[open] == DTM_UNSET);
    // global invariants
    uint64_t mates = 0, invalid_w = 0;
    for (uint64_t c = 0; c < g.index().size(); ++c) {
        if (g.dtm(Color::Black)[c] == 0) mates++;
        if (g.dtm(Color::White)[c] == DTM_INVALID) invalid_w++;
        CHECK(g.dtm(Color::White)[c] != 0);            // wtm can never be dtm 0
    }
    CHECK(mates > 0); CHECK(invalid_w > 0);
}
TEST_CASE("init pass on Kvk finds no mates") {
    SliceGen g(*Material::parse("Kvk"), {});
    g.init_pass();
    for (uint64_t c = 0; c < g.index().size(); ++c)
        CHECK(g.dtm(Color::Black)[c] != 0);
}
```

- [ ] **Step 2: Run to verify failure** — `make test`.

- [ ] **Step 3: Implement `SliceGen` construction + init_pass**

```cpp
SliceGen::SliceGen(const Material& m, const GenOptions& opt)
    : mat_(m), opt_(opt), idx_(m), ps_(idx_.size()) {
    for (int s = 0; s < 2; ++s) { dtm_[s].assign(ps_, DTM_UNSET); cnt_[s].assign(ps_, 0); }
}
void SliceGen::init_pass() {
    std::vector<PlacedPiece> pp; Board b;
    for (uint64_t c = 0; c < ps_; ++c) {
        if (!idx_.decode(c, pp)) { dtm_[0][c] = dtm_[1][c] = DTM_INVALID; continue; }
        auto e = idx_.encode(pp);
        if (!e || *e != c)       { dtm_[0][c] = dtm_[1][c] = DTM_INVALID; continue; }  // non-canonical duplicate
        for (int s = 0; s < 2; ++s) {
            b.reset(pp, (Color)s);
            if (b.opponent_in_check()) { dtm_[s][c] = DTM_INVALID; continue; }
            if (s == 1 && b.state() == PosState::Checkmate) dtm_[1][c] = 0;
        }
    }
}
```
(Kings adjacent and pawns on ranks 1/8 cannot be decoded at all — the KK table and the 48-radix exclude them by construction.)

- [ ] **Step 4: Run tests** — `make test`, expect PASS.
- [ ] **Step 5: Commit** — `git add src/generator tests/cpp/test_generator_init.cpp CMakeLists.txt && git commit -m "feat: generator init pass (invalid cells, mate seeds)"`

---

### Task 10: Generator — scan passes, cross-slice lookups, finalize; KQvk validated

**Files:**
- Create: `src/generator/eval.h`, `tests/cpp/test_generator_kqvk.cpp`
- Modify: `src/generator/generator.h`, `src/generator/generator.cpp`, `CMakeLists.txt`

**Interfaces:**
- Produces:

```cpp
// src/generator/eval.h  (header-only)
namespace hm {
// LookupFn: ValuePair(Board&) — value of an EP-less position (board's material may
// differ from the caller's slice; the function routes to the right table).
// eval_board: value of the position in b including any EP rights b carries.
// If b has an EP square, every legal EP capture r contributes (1 + value(after r));
// the EP-less table value contributes as-is; result is the min, counts summed over
// branches achieving the min (saturating).
template <class LookupFn>
ValuePair eval_board(Board& b, LookupFn&& lookup) {
    int best = INT_MAX; unsigned count = 0;
    ValuePair base = lookup(b);
    if (base.dtm <= DTM_MAX) { best = base.dtm; count = base.count; }
    if (b.ep_square() >= 0) {
        for (const Move& r : b.legal_moves()) {
            if (!r.is_ep()) continue;
            b.make(r);
            ValuePair v = lookup(b);                  // EP capture never creates new EP rights
            b.unmake(r);
            if (v.dtm > DTM_MAX) continue;
            int via = v.dtm + 1;
            if (via < best) { best = via; count = v.count; }
            else if (via == best) count = std::min(255u, count + (unsigned)v.count);
        }
    }
    if (best == INT_MAX) return {DTM_UNSOLVABLE, 0};
    return {(uint8_t)best, (uint8_t)count};
}
}
```
- `SliceGen` additions: `scan_pass`, `run_all_passes`, `finalize_and_write`, plus internal `SubTables` (loaded finished tables of successor materials) and `lookup_epless(Board&)`.
- `generate(root, opt)`: closure driver.

- [ ] **Step 1: Write the failing tests**

`tests/cpp/test_generator_kqvk.cpp`:
```cpp
#include <catch2/catch_test_macros.hpp>
#include "generator/generator.h"
#include "generator/oracle.h"
#include "format/table_file.h"
#include "indexing/slice_index.h"
#include "chess/board.h"
#include <filesystem>
#include <random>
using namespace hm;
static std::string tdir() {
    auto d = std::filesystem::temp_directory_path() / "hm_gen_kqvk";
    std::filesystem::remove_all(d); std::filesystem::create_directories(d);
    return d.string();
}
static ValuePair probe_file(const std::string& dir, const std::string& fen) {
    auto b = Board::from_fen(fen); REQUIRE(b);
    Material m = Material::of(b->pieces());
    auto r = TableReader::open(dir + "/" + m.name() + ".hm"); REQUIRE(r);
    SliceIndex idx(m);
    auto e = idx.encode(b->pieces()); REQUIRE(e);
    return r->get(b->stm(), *e);
}
TEST_CASE("generate KQvk end to end") {
    GenOptions opt; opt.tables_dir = tdir();
    auto written = generate(*Material::parse("KQvk"), opt);
    REQUIRE(written.size() == 2);                     // Kvk then KQvk
    CHECK(std::filesystem::exists(opt.tables_dir + "/Kvk.hm"));
    CHECK(std::filesystem::exists(opt.tables_dir + "/KQvk.hm"));

    // goldens (hand-verified in Task 8)
    CHECK(probe_file(opt.tables_dir, "7k/6Q1/5K2/8/8/8/8/8 b - - 0 1").dtm == 0);
    CHECK(probe_file(opt.tables_dir, "7k/8/5K2/8/8/8/8/6Q1 w - - 0 1").dtm == 1);
    CHECK(probe_file(opt.tables_dir, "8/7k/5K2/8/8/8/8/6Q1 b - - 0 1").dtm == 2);
    CHECK(probe_file(opt.tables_dir, "8/7k/5K2/8/8/8/8/Q7 w - - 0 1").dtm == 3);

    // parity invariant + Kvk all unsolvable
    auto kvk = TableReader::open(opt.tables_dir + "/Kvk.hm");
    for (uint64_t c = 0; c < kvk->plane_size(); ++c) {
        CHECK(kvk->get(Color::White, c).dtm >= DTM_INVALID);
        CHECK(kvk->get(Color::Black, c).dtm >= DTM_INVALID);
    }
    auto kq = TableReader::open(opt.tables_dir + "/KQvk.hm");
    SliceIndex idx(*Material::parse("KQvk"));
    for (uint64_t c = 0; c < kq->plane_size(); ++c) {
        uint8_t w = kq->get(Color::White, c).dtm, b = kq->get(Color::Black, c).dtm;
        if (w <= DTM_MAX) CHECK(w % 2 == 1);
        if (b <= DTM_MAX) CHECK(b % 2 == 0);
    }

    // oracle cross-check on 300 random valid cells
    std::mt19937_64 rng(7);
    std::vector<PlacedPiece> pp;
    int checked = 0;
    while (checked < 300) {
        uint64_t c = rng() % kq->plane_size();
        Color stm = (rng() & 1) ? Color::White : Color::Black;
        uint8_t d = kq->get(stm, c).dtm;
        if (d == DTM_INVALID) continue;
        REQUIRE(idx.decode(c, pp));
        Board b = Board::from_pieces(pp, stm);
        auto o = oracle_solve(b, d <= DTM_MAX ? d : 16);
        if (d <= DTM_MAX) { REQUIRE(o); CHECK(o->dtm == d); }
        else               CHECK(!o);                 // unsolvable: no mate within 16 plies
        checked++;
    }
}
```

- [ ] **Step 2: Run to verify failure** — `make test`.

- [ ] **Step 3: Implement scan passes and driver**

Additions to `generator.cpp`:
```cpp
// SubTables: finished successor tables. Declared in generator.h (it is a SliceGen member).
struct SubTables {
    std::map<std::string, std::pair<TableReader, SliceIndex>> t_;
    void load_for(const Material& m, const std::string& dir) {
        for (auto& s : m.successors()) {
            if (t_.count(s.name())) continue;
            auto r = TableReader::open(dir + "/" + s.name() + ".hm");
            if (!r) throw std::runtime_error("missing sub-table " + s.name());
            t_.emplace(s.name(), std::pair(std::move(*r), SliceIndex(s)));
        }
    }
    ValuePair lookup(const Material& m, const std::vector<PlacedPiece>& pp, Color stm) const {
        auto& [rd, si] = t_.at(m.name());
        auto e = si.encode(pp);                        // legal position => always encodable
        return rd.get(stm, *e);
    }
};

ValuePair SliceGen::lookup_epless(Board& b) {
    auto pp = b.pieces();
    Material m = Material::of(pp);
    if (m == mat_) {
        auto e = idx_.encode(pp);
        int s = (int)b.stm();
        return { dtm_[s][*e], cnt_[s][*e] };
    }
    return subs_.lookup(m, pp, b.stm());
}

bool SliceGen::scan_pass(int d) {
    Color mover = (d % 2) ? Color::White : Color::Black;
    int s = (int)mover;
    bool any = false;
    std::vector<PlacedPiece> pp; Board b;
    for (uint64_t c = 0; c < ps_; ++c) {
        if (dtm_[s][c] != DTM_UNSET) continue;
        idx_.decode(c, pp);                            // UNSET cells always decode
        b.reset(pp, mover);
        for (const Move& m : b.legal_moves()) {
            b.make(m);
            ValuePair v = eval_board(b, [this](Board& x) { return lookup_epless(x); });
            b.unmake(m);
            if (v.dtm == d - 1) { dtm_[s][c] = (uint8_t)d; any = true; break; }
        }
    }
    return any;
}

void SliceGen::run_all_passes() {
    subs_.load_for(mat_, opt_.tables_dir);
    init_pass();
    max_dtm_ = -1;
    { bool any0 = false; for (uint64_t c = 0; c < ps_; ++c) if (dtm_[1][c] == 0) { any0 = true; break; }
      if (any0) max_dtm_ = 0; }
    int misses = 0;
    for (int d = 1; d <= DTM_MAX && misses < 2; ++d) {
        if (scan_pass(d)) { max_dtm_ = d; misses = 0; } else misses++;
    }
}

void SliceGen::finalize_and_write() {
    for (int s = 0; s < 2; ++s)
        for (uint64_t c = 0; c < ps_; ++c)
            if (dtm_[s][c] == DTM_UNSET) dtm_[s][c] = DTM_UNSOLVABLE;
    std::string meta = "{}";                           // extended in Task 13
    std::filesystem::create_directories(opt_.tables_dir);
    TableWriter::write(opt_.tables_dir + "/" + mat_.name() + ".hm", mat_, ps_,
                       max_dtm_ < 0 ? DTM_UNSOLVABLE : (uint8_t)max_dtm_, meta,
                       dtm_[0].data(), dtm_[1].data(), cnt_[0].data(), cnt_[1].data());
}

std::vector<std::string> generate(const Material& root, const GenOptions& opt) {
    std::vector<std::string> written;
    for (auto& m : Material::closure_topo(root)) {
        std::string path = opt.tables_dir + "/" + m.name() + ".hm";
        if (std::filesystem::exists(path)) continue;
        SliceGen g(m, opt);
        g.run_all_passes();
        g.count_sweep();                               // no-op until Task 12 implements it
        g.finalize_and_write();
        written.push_back(path);
    }
    return written;
}
```
`count_sweep()` gets an empty body for now (declared in Task 9's header). Why two consecutive missing passes terminate: pass d only assigns cells of one parity; a single empty pass can be followed by a productive pass of the other parity, two empty passes cannot (a new value d would need a successor valued d−1 assigned in the previous, empty pass).

- [ ] **Step 4: Run tests** — `make test`, expect PASS. The KQvk oracle cross-check is the correctness gate for the whole pipeline so far.
- [ ] **Step 5: Commit** — `git add src/generator tests/cpp/test_generator_kqvk.cpp CMakeLists.txt && git commit -m "feat: forward-scan generation with cross-slice lookups, KQvk oracle-verified"`

---

### Task 11: Promotions and en passant correctness

**Files:**
- Create: `tests/cpp/test_generator_pawns.cpp`
- Modify: `CMakeLists.txt`

No new production code is expected — this task *proves* the pawn paths of Tasks 2/10 with targeted tests, and fixes whatever they flush out.

- [ ] **Step 1: Write the tests**

`tests/cpp/test_generator_pawns.cpp`:
```cpp
#include <catch2/catch_test_macros.hpp>
#include "generator/generator.h"
#include "generator/oracle.h"
#include "generator/eval.h"
#include "format/table_file.h"
#include "indexing/slice_index.h"
#include "chess/board.h"
#include <filesystem>
#include <random>
using namespace hm;
static std::string tdir(const char* name) {
    auto d = std::filesystem::temp_directory_path() / name;
    std::filesystem::remove_all(d); std::filesystem::create_directories(d);
    return d.string();
}
TEST_CASE("eval_board combines EP branch with table value") {
    // wK a1, bK a8, wP e5, bp d5; wtm with EP right on d6 (black just played d7-d5).
    Board b = Board::from_pieces({
        {{Color::White, PieceType::King}, 0},  {{Color::Black, PieceType::King}, 56},
        {{Color::White, PieceType::Pawn}, 36}, {{Color::Black, PieceType::Pawn}, 35}},
        Color::White, /*ep=*/43);
    REQUIRE(b.ep_square() == 43);
    // canned lookup: EP-less base value 9; position after exd6 e.p. valued 4.
    auto lookup = [&](Board& x) -> ValuePair {
        return x.pieces().size() == 4 ? ValuePair{9, 3} : ValuePair{4, 2};
    };
    ValuePair v = eval_board(b, lookup);
    CHECK((int)v.dtm == 5);                            // min(9, 1+4)
    CHECK((int)v.count == 2);                          // only the EP branch achieves 5
    // tie case: base 5 -> counts add up
    auto lookup2 = [&](Board& x) -> ValuePair {
        return x.pieces().size() == 4 ? ValuePair{5, 3} : ValuePair{4, 2};
    };
    ValuePair v2 = eval_board(b, lookup2);
    CHECK((int)v2.dtm == 5); CHECK((int)v2.count == 5);
}
TEST_CASE("KPvk: promotions carry mate potential across slices") {
    GenOptions opt; opt.tables_dir = tdir("hm_gen_kpvk");
    generate(*Material::parse("KPvk"), opt);
    // KNvk and KBvk have no legal checkmate at all -> fully unsolvable
    for (const char* n : {"KNvk", "KBvk"}) {
        auto r = TableReader::open(opt.tables_dir + std::string("/") + n + ".hm"); REQUIRE(r);
        for (uint64_t c = 0; c < r->plane_size(); ++c) {
            CHECK(r->get(Color::White, c).dtm >= DTM_INVALID);
            CHECK(r->get(Color::Black, c).dtm >= DTM_INVALID);
        }
    }
    // KPvk itself is solvable ONLY via promotion (P alone can't mate) -> finite cells must exist
    auto r = TableReader::open(opt.tables_dir + "/KPvk.hm"); REQUIRE(r);
    uint64_t finite = 0;
    for (uint64_t c = 0; c < r->plane_size(); ++c)
        if (r->get(Color::White, c).dtm <= DTM_MAX) finite++;
    CHECK(finite > 0);
    // oracle cross-check on 200 random KPvk cells
    SliceIndex idx(*Material::parse("KPvk"));
    std::mt19937_64 rng(11); std::vector<PlacedPiece> pp; int checked = 0;
    while (checked < 200) {
        uint64_t c = rng() % r->plane_size();
        Color stm = (rng() & 1) ? Color::White : Color::Black;
        uint8_t d = r->get(stm, c).dtm;
        if (d > DTM_MAX) continue;                     // skip invalid/unsolvable (horizon issues)
        REQUIRE(idx.decode(c, pp));
        Board b = Board::from_pieces(pp, stm);
        auto o = oracle_solve(b, d);
        REQUIRE(o); CHECK(o->dtm == d);
        checked++;
    }
}
TEST_CASE("KPvkp: EP-relevant positions match the oracle", "[slow]") {
    GenOptions opt; opt.tables_dir = tdir("hm_gen_kpvkp");
    generate(*Material::parse("KPvkp"), opt);          // builds the full 36-slice closure
    auto r = TableReader::open(opt.tables_dir + "/KPvkp.hm"); REQUIRE(r);
    SliceIndex idx(*Material::parse("KPvkp"));
    // sample cells where a double push is available and pawns are on adjacent files
    std::mt19937_64 rng(13); std::vector<PlacedPiece> pp; int checked = 0;
    while (checked < 100) {
        uint64_t c = rng() % r->plane_size();
        if (!idx.decode(c, pp)) continue;
        int wp = -1, bp = -1;
        for (auto& p : pp) if (p.piece.type == PieceType::Pawn)
            (p.piece.color == Color::White ? wp : bp) = p.square;
        if (sq_rank(wp) != 1 || std::abs(sq_file(wp) - sq_file(bp)) != 1 || sq_rank(bp) != 3)
            continue;                                  // want: wP on rank 2, bp on rank 4 adjacent file
        for (Color stm : {Color::White, Color::Black}) {
            uint8_t d = r->get(stm, c).dtm;
            if (d > DTM_MAX) continue;
            Board b = Board::from_pieces(pp, stm);
            auto o = oracle_solve(b, d);
            REQUIRE(o); CHECK(o->dtm == d);            // oracle plays real EP; table used eval_board
        }
        checked++;
    }
}
```
Register the `[slow]` tag as excluded by default: in `CMakeLists.txt`, `catch_discover_tests(helpmate_tests TEST_SPEC "~[slow]")`, and add a dedicated target/note: run slow tests manually with `./build/helpmate_tests "[slow]"`.

- [ ] **Step 2: Run tests** — `make test`. Fix any adapter/eval bugs these expose (EP flag decoding and pawn-direction bugs typically surface here). Run the slow KPvkp test once manually before committing: `./build/helpmate_tests "[slow]"`.
- [ ] **Step 3: Commit** — `git add tests/cpp/test_generator_pawns.cpp CMakeLists.txt && git commit -m "test: promotion and en-passant correctness vs oracle"`

---

### Task 12: Count sweep

**Files:**
- Create: `tests/cpp/test_counts.cpp`
- Modify: `src/generator/generator.cpp` (implement `count_sweep`), `CMakeLists.txt`

**Interfaces:**
- Consumes: `SliceGen` internals (T9/T10), `eval_board` (T10), oracle counts (T8).
- Produces: filled `cnt_` planes: `cnt = 0` for invalid/unsolvable, else the saturating number of optimal lines.

- [ ] **Step 1: Write the failing tests**

`tests/cpp/test_counts.cpp`:
```cpp
#include <catch2/catch_test_macros.hpp>
#include "generator/generator.h"
#include "generator/oracle.h"
#include "format/table_file.h"
#include "indexing/slice_index.h"
#include "chess/board.h"
#include <filesystem>
#include <random>
using namespace hm;
TEST_CASE("KQvk counts match the oracle") {
    auto d = std::filesystem::temp_directory_path() / "hm_counts";
    std::filesystem::remove_all(d); std::filesystem::create_directories(d);
    GenOptions opt; opt.tables_dir = d.string();
    generate(*Material::parse("KQvk"), opt);
    auto r = TableReader::open(opt.tables_dir + "/KQvk.hm"); REQUIRE(r);
    SliceIndex idx(*Material::parse("KQvk"));

    // goldens (hand-verified in Task 8)
    auto probe = [&](const std::string& fen) {
        auto b = Board::from_fen(fen); REQUIRE(b);
        return r->get(b->stm(), *idx.encode(b->pieces()));
    };
    CHECK((int)probe("7k/6Q1/5K2/8/8/8/8/8 b - - 0 1").count == 1);   // dtm 0
    CHECK((int)probe("7k/8/5K2/8/8/8/8/6Q1 w - - 0 1").count == 1);   // dtm 1
    CHECK((int)probe("8/7k/5K2/8/8/8/8/6Q1 b - - 0 1").count == 1);   // dtm 2

    // structural invariants + oracle cross-check
    std::mt19937_64 rng(23); std::vector<PlacedPiece> pp; int checked = 0;
    for (uint64_t c = 0; c < r->plane_size(); ++c)
        for (Color stm : {Color::White, Color::Black}) {
            ValuePair v = r->get(stm, c);
            if (v.dtm > DTM_MAX) CHECK((int)v.count == 0);
            else                 CHECK((int)v.count >= 1);
        }
    while (checked < 150) {
        uint64_t c = rng() % r->plane_size();
        Color stm = (rng() & 1) ? Color::White : Color::Black;
        ValuePair v = r->get(stm, c);
        if (v.dtm > DTM_MAX) continue;
        REQUIRE(idx.decode(c, pp));
        Board b = Board::from_pieces(pp, stm);
        auto o = oracle_solve(b, v.dtm);
        REQUIRE(o);
        CHECK(o->count == (int)v.count);              // both saturate at 255
        checked++;
    }
}
TEST_CASE("promotion mate counts Q and R separately") {
    auto d = std::filesystem::temp_directory_path() / "hm_counts_p";
    std::filesystem::remove_all(d); std::filesystem::create_directories(d);
    GenOptions opt; opt.tables_dir = d.string();
    generate(*Material::parse("KPvk"), opt);
    auto r = TableReader::open(opt.tables_dir + "/KPvk.hm"); REQUIRE(r);
    SliceIndex idx(*Material::parse("KPvk"));
    auto b = Board::from_fen("6k1/4P3/6K1/8/8/8/8/8 w - - 0 1"); REQUIRE(b);
    ValuePair v = r->get(Color::White, *idx.encode(b->pieces()));
    CHECK((int)v.dtm == 1);
    CHECK((int)v.count == 2);                         // e8=Q# and e8=R# (golden G4)
}
```

- [ ] **Step 2: Run to verify failure** — `make test` (counts currently all 0 for solvable cells).

- [ ] **Step 3: Implement `count_sweep`**

In `generator.cpp` (replace the empty body):
```cpp
void SliceGen::count_sweep() {
    for (uint64_t c = 0; c < ps_; ++c) if (dtm_[1][c] == 0) cnt_[1][c] = 1;
    std::vector<PlacedPiece> pp; Board b;
    for (int d = 1; d <= max_dtm_; ++d) {
        int s = (d % 2) ? 0 : 1;
        for (uint64_t c = 0; c < ps_; ++c) {
            if (dtm_[s][c] != d) continue;
            idx_.decode(c, pp);
            b.reset(pp, (Color)s);
            unsigned total = 0;
            for (const Move& m : b.legal_moves()) {
                b.make(m);
                ValuePair v = eval_board(b, [this](Board& x) { return lookup_epless(x); });
                b.unmake(m);
                if (v.dtm == d - 1) total = std::min(255u, total + (unsigned)v.count);
            }
            cnt_[s][c] = (uint8_t)total;              // >= 1 by construction of dtm
        }
    }
}
```
Correctness note (also as a comment in code): pass `d` reads only counts of cells with dtm `d−1`, which the previous iteration finalized; sub-slice tables were fully counted before this slice (topological build order); `eval_board` merges EP branches with the same min/sum rule.

- [ ] **Step 4: Run tests** — `make test`, expect PASS. The oracle count equality is the gate: the oracle counts by exhaustive exact-length enumeration, the table by DP — two independent methods.
- [ ] **Step 5: Commit** — `git add src/generator/generator.cpp tests/cpp/test_counts.cpp CMakeLists.txt && git commit -m "feat: optimal-line count sweep, oracle-verified"`

---

### Task 13: Stats and sidecar JSON

**Files:**
- Create: `tests/cpp/test_stats.cpp`
- Modify: `src/generator/generator.cpp` (`finalize_and_write` fills real stats), `src/generator/generator.h` (add `nlohmann::json stats_json() const;` to `SliceGen`), `CMakeLists.txt`

**Interfaces:**
- Produces: `tables/<NAME>.stats.json` sidecar + the same JSON embedded as the `.hm` meta block. Shape:

```json
{
  "material": "KQvk", "plane_size": 29568, "max_dtm": 10,
  "cells": {"invalid": {"wtm": 0, "btm": 0}, "unsolvable": {"wtm": 0, "btm": 0}},
  "dtm_histogram": {"wtm": {"1": 0}, "btm": {"0": 0}},
  "uniqueness": {"btm": {"2": {"1": 0, "2": 0, "255": 0}}, "wtm": {}},
  "deepest": ["<fen>"], "deepest_unique": ["<fen>"],
  "generator_version": "0.1.0"
}
```
`uniqueness[stm][dtm][count]` = number of cells; count key `"255"` means "≥255". `deepest`: up to 5 FENs at `max_dtm`; `deepest_unique`: up to 5 FENs at the highest dtm that has a cell with count 1.

- [ ] **Step 1: Write the failing tests**

`tests/cpp/test_stats.cpp`:
```cpp
#include <catch2/catch_test_macros.hpp>
#include "generator/generator.h"
#include "format/table_file.h"
#include "chess/board.h"
#include <nlohmann/json.hpp>
#include <filesystem>
#include <fstream>
using namespace hm;
TEST_CASE("stats sidecar is written and consistent") {
    auto d = std::filesystem::temp_directory_path() / "hm_stats";
    std::filesystem::remove_all(d); std::filesystem::create_directories(d);
    GenOptions opt; opt.tables_dir = d.string();
    generate(*Material::parse("KQvk"), opt);
    std::ifstream f(opt.tables_dir + "/KQvk.stats.json"); REQUIRE(f.good());
    auto j = nlohmann::json::parse(f);
    CHECK(j["material"] == "KQvk");
    CHECK(j["plane_size"] == 462ull * 64);
    int maxd = j["max_dtm"];
    CHECK(maxd >= 3);                                  // golden G3 proves >= 3
    // histogram sums must account for every cell
    uint64_t total_b = 0;
    for (auto& [k, v] : j["dtm_histogram"]["btm"].items()) total_b += (uint64_t)v;
    total_b += (uint64_t)j["cells"]["invalid"]["btm"] + (uint64_t)j["cells"]["unsolvable"]["btm"];
    CHECK(total_b == 462ull * 64);
    // deepest FENs probe back to max_dtm
    REQUIRE(!j["deepest"].empty());
    auto b = Board::from_fen(j["deepest"][0]); REQUIRE(b);
    auto r = TableReader::open(opt.tables_dir + "/KQvk.hm");
    SliceIndex idx(*Material::parse("KQvk"));
    CHECK((int)r->get(b->stm(), *idx.encode(b->pieces())).dtm == maxd);
    // embedded meta == sidecar
    CHECK(nlohmann::json::parse(r->meta_json()) == j);
    // uniqueness histogram exists for some depth
    CHECK(j.contains("uniqueness"));
}
```

- [ ] **Step 2: Run to verify failure** — `make test`.

- [ ] **Step 3: Implement**

`stats_json()` scans the four planes once, building the counters described above; deepest cells are collected during the scan (decode → `Board::from_pieces` → `fen()`; the FEN's stm is the plane the cell came from). `finalize_and_write` writes the JSON both into the `.hm` meta block and to `<NAME>.stats.json` (pretty-printed, `dump(2)`).

- [ ] **Step 4: Run tests** — `make test`, expect PASS.
- [ ] **Step 5: Commit** — `git add src/generator tests/cpp/test_stats.cpp CMakeLists.txt && git commit -m "feat: per-slice stats with uniqueness histogram and deepest positions"`

---

### Task 14: Multithreading

**Files:**
- Create: `src/generator/parallel.h`, `tests/cpp/test_threads.cpp`
- Modify: `src/generator/generator.cpp` (use `parallel_for` in init/scan/count loops), `CMakeLists.txt`

**Interfaces:**
- Produces:

```cpp
// src/generator/parallel.h
namespace hm {
// Splits [0,n) into contiguous chunks over `threads` std::threads (1 -> inline call).
// fn(begin, end) must only write to cells it owns and shared atomics.
void parallel_for(uint64_t n, int threads, const std::function<void(uint64_t, uint64_t)>& fn);
}
```
- `GenOptions::threads` now honored. Safety argument (goes into a code comment): pass `d` writes only value `d` into UNSET cells of one plane and reads (a) the other-parity plane, which this pass never writes, (b) finished sub-tables, (c) same-plane values — never: a cell's successors after one ply always have the other side to move. Each worker owns a disjoint cell range; the only shared write is the `any` flag (atomic).

- [ ] **Step 1: Write the failing test**

`tests/cpp/test_threads.cpp`:
```cpp
#include <catch2/catch_test_macros.hpp>
#include "generator/generator.h"
#include "format/table_file.h"
#include <filesystem>
#include <fstream>
using namespace hm;
static std::string file_bytes(const std::string& p) {
    std::ifstream f(p, std::ios::binary);
    return std::string(std::istreambuf_iterator<char>(f), {});
}
TEST_CASE("4-thread generation is byte-identical to 1-thread") {
    auto base = std::filesystem::temp_directory_path();
    for (int th : {1, 4}) {
        auto d = base / ("hm_thr_" + std::to_string(th));
        std::filesystem::remove_all(d); std::filesystem::create_directories(d);
        GenOptions opt; opt.tables_dir = d.string(); opt.threads = th;
        generate(*Material::parse("KPvk"), opt);
    }
    for (const char* n : {"Kvk", "KQvk", "KRvk", "KBvk", "KNvk", "KPvk"}) {
        auto a = file_bytes((base / "hm_thr_1" / (std::string(n) + ".hm")).string());
        auto b = file_bytes((base / "hm_thr_4" / (std::string(n) + ".hm")).string());
        REQUIRE(!a.empty());
        CHECK(a == b);
    }
}
```

- [ ] **Step 2: Run to verify failure** — currently `threads` is ignored, so this PASSES trivially. To make it a real test first: implement `parallel_for` and convert `init_pass`/`scan_pass`/`count_sweep` loops; the test then guards determinism. (This task is refactor-with-safety-net rather than red-green: the whole existing suite is the net.)

- [ ] **Step 3: Implement**

`parallel_for`: chunk = `(n + threads - 1) / threads`; spawn `std::thread`s, join all. In `generator.cpp` each worker gets its own `Board b; std::vector<PlacedPiece> pp;` (declare inside the lambda); `scan_pass` uses `std::atomic<bool> any`. Timestamps or thread counts must NOT enter the stats JSON (byte-identical output is a feature).

- [ ] **Step 4: Run the full suite** — `make test`, all green including determinism test.
- [ ] **Step 5: Commit** — `git add src/generator tests/cpp/test_threads.cpp CMakeLists.txt && git commit -m "feat: multithreaded generation, deterministic output"`

---

### Task 15: Probe library

**Files:**
- Create: `src/probe/tablebase.h`, `src/probe/tablebase.cpp`, `tests/cpp/test_probe.cpp`
- Modify: `CMakeLists.txt`

**Interfaces:**
- Consumes: `TableReader`, `SliceIndex`, `Material`, `Board`, `eval_board`, `san`.
- Produces:

```cpp
namespace hm {
class Tablebase {
public:
    explicit Tablebase(std::string dir);              // lazy-loads .hm files on demand
    struct Probe { int dtm; int count; bool flipped; };  // flipped: colors were swapped to match a slice
    // nullopt = position is valid but unsolvable. Throws MissingTableError (with the
    // slice names tried) or std::invalid_argument (bad FEN / castling rights).
    std::optional<Probe> probe(const std::string& fen) const;
    std::vector<std::string> line(const std::string& fen) const;              // one optimal line, SAN
    std::vector<std::vector<std::string>> lines(const std::string& fen, int max = 100) const;
    // stream FENs of canonical cells with given dtm (and count, -1 = any); stop when cb returns false
    void mine(const Material&, int dtm, int count, const std::function<bool(const std::string&)>& cb) const;
    std::string stats_json(const Material&) const;    // sidecar content; throws MissingTableError
    static std::string h_notation(int dtm, Color stm);   // "h#2", "h#1.5", "h#0"
};
struct MissingTableError : std::runtime_error { using std::runtime_error::runtime_error; };
}
```
Color flip: mirror ranks (`sq ^ 56`), swap piece colors, flip stm, mirror any EP square — exact because castling doesn't exist here. `probe` tries the position's own material first; if that slice file is missing, probes the flipped board against the flipped material name; `flipped=true` in the result means "the mated side is White in the caller's coordinates". Values (incl. EP rights in the FEN) go through `eval_board` with a lookup that routes to the loaded tables.

- [ ] **Step 1: Write the failing tests**

`tests/cpp/test_probe.cpp`:
```cpp
#include <catch2/catch_test_macros.hpp>
#include "probe/tablebase.h"
#include "generator/generator.h"
#include <filesystem>
using namespace hm;
static std::string gen_dir() {                        // one shared generated dir per test binary run
    static std::string dir = [] {
        auto d = std::filesystem::temp_directory_path() / "hm_probe";
        std::filesystem::remove_all(d); std::filesystem::create_directories(d);
        GenOptions opt; opt.tables_dir = d.string();
        generate(*Material::parse("KQvk"), opt);
        generate(*Material::parse("KPvk"), opt);
        return opt.tables_dir;
    }();
    return dir;
}
TEST_CASE("probe goldens with h-notation") {
    Tablebase tb(gen_dir());
    auto p = tb.probe("8/7k/5K2/8/8/8/8/6Q1 b - - 0 1");
    REQUIRE(p); CHECK(p->dtm == 2); CHECK(p->count == 1); CHECK(!p->flipped);
    CHECK(Tablebase::h_notation(2, Color::Black) == "h#1");
    CHECK(Tablebase::h_notation(1, Color::White) == "h#0.5");
    CHECK(Tablebase::h_notation(0, Color::Black) == "h#0");
}
TEST_CASE("probe color-flipped position") {
    Tablebase tb(gen_dir());
    // color-flip of the dtm-2 golden: White king mated by black queen; only KQvk exists
    auto p = tb.probe("6q1/8/8/8/8/5k2/7K/8 w - - 0 1");
    REQUIRE(p); CHECK(p->dtm == 2); CHECK(p->flipped);
}
TEST_CASE("line reconstruction") {
    Tablebase tb(gen_dir());
    auto l = tb.line("8/7k/5K2/8/8/8/8/6Q1 b - - 0 1");
    REQUIRE(l.size() == 2);
    CHECK(l[0] == "Kh8"); CHECK(l[1] == "Qg7#");
    auto all = tb.lines("8/7k/5K2/8/8/8/8/6Q1 b - - 0 1");
    CHECK(all.size() == 1);                            // count == 1
    auto promo = tb.lines("6k1/4P3/6K1/8/8/8/8/8 w - - 0 1");
    CHECK(promo.size() == 2);                          // e8=Q# and e8=R#
}
TEST_CASE("mine finds unique-solution cells") {
    Tablebase tb(gen_dir());
    int found = 0;
    tb.mine(*Material::parse("KQvk"), 2, 1, [&](const std::string& fen) {
        auto p = tb.probe(fen);
        REQUIRE(p); CHECK(p->dtm == 2); CHECK(p->count == 1);
        return ++found < 10;
    });
    CHECK(found == 10);
}
TEST_CASE("errors") {
    Tablebase tb(gen_dir());
    CHECK_THROWS_AS(tb.probe("8/8/8/8/3n4/4k3/8/4K3 w - - 0 1"), MissingTableError);  // KvkN not built
    CHECK_THROWS_AS(tb.probe("garbage"), std::invalid_argument);
    CHECK_THROWS_AS(tb.stats_json(*Material::parse("KRvkr")), MissingTableError);
}
TEST_CASE("unsolvable probes to nullopt") {
    Tablebase tb(gen_dir());
    CHECK(!tb.probe("8/8/8/8/8/4k3/8/4K3 w - - 0 1"));   // Kvk was built as part of closures
}
```

- [ ] **Step 2: Run to verify failure** — `make test`.

- [ ] **Step 3: Implement**

`tablebase.cpp` key pieces:
```cpp
struct Tablebase::Slice { TableReader reader; SliceIndex index; };
const Tablebase::Slice* Tablebase::load(const Material& m) const {   // cache + nullptr if file missing
    std::lock_guard lk(mu_);
    auto it = cache_.find(m.name());
    if (it != cache_.end()) return it->second.get();
    auto r = TableReader::open(dir_ + "/" + m.name() + ".hm");
    auto& slot = cache_[m.name()];
    if (r) slot = std::make_unique<Slice>(Slice{std::move(*r), SliceIndex(m)});
    return slot.get();
}
ValuePair Tablebase::value_of(Board& b) const {        // EP-aware, throws if slice missing
    auto lookup = [this](Board& x) -> ValuePair {
        Material m = Material::of(x.pieces());
        const Slice* s = load(m);
        if (!s) throw MissingTableError("no table for " + m.name());
        return s->reader.get(x.stm(), *s->index.encode(x.pieces()));
    };
    return eval_board(b, lookup);
}
std::optional<Tablebase::Probe> Tablebase::probe(const std::string& fen) const {
    auto b = Board::from_fen(fen);
    if (!b) throw std::invalid_argument("bad FEN (or castling rights): " + fen);
    Material m = Material::of(b->pieces());
    bool flipped = false;
    Board target = *b;
    if (!load(m)) {
        target = flip_colors(*b); flipped = true;
        if (!load(Material::of(target.pieces())))
            throw MissingTableError("no table for " + m.name() + " nor its color flip");
    }
    ValuePair v = value_of(target);
    if (v.dtm > DTM_MAX) return std::nullopt;          // UNSOLVABLE (INVALID can't reach here: FEN was legal)
    return Probe{(int)v.dtm, (int)v.count, flipped};
}
```
`line`: loop — `v = value_of(b)`; if `v.dtm == 0` stop; among `b.legal_moves()` find the first `m` with `eval` of successor `== v.dtm - 1` (EP-aware via `value_of`), emit `san(b, m)`, `b.make(m)`. `lines`: same but recursive over all optimal moves, capped at `max`. `mine`: iterate the plane of parity-matching stm; skip cells whose dtm/count don't match; `decode` → `Board::from_pieces` → `fen()` → callback. `flip_colors`: free function in `tablebase.cpp` building the mirrored piece list (`sq ^ 56`, color swapped) + flipped stm + mirrored EP square from `b.ep_square()`.

- [ ] **Step 4: Run tests** — `make test`, expect PASS.
- [ ] **Step 5: Commit** — `git add src/probe tests/cpp/test_probe.cpp CMakeLists.txt && git commit -m "feat: Tablebase probe library with lines, mining and color flip"`

---

### Task 16: CLI

**Files:**
- Create: `src/cli/main.cpp`
- Modify: `CMakeLists.txt` (add `helpmate` executable + CLI ctest cases)

**Interfaces:**
- Consumes: `generate`, `Tablebase`, `Material`.
- Produces the user-facing commands:

```
helpmate gen <MATERIAL> [--tables DIR] [--threads N]
helpmate probe <FEN> [--tables DIR]
helpmate line <FEN> [--tables DIR] [--all] [--max N]
helpmate stats <MATERIAL> [--tables DIR]
helpmate mine <MATERIAL> --dtm D [--count C] [--max N] [--tables DIR]
```
Exit codes: 0 success (including "unsolvable" answers), 2 missing table, 3 bad usage/input.

- [ ] **Step 1: Write the failing tests (ctest level)**

Append to `CMakeLists.txt`:
```cmake
add_executable(helpmate src/cli/main.cpp)
target_link_libraries(helpmate PRIVATE helpmate_core)

set(CLI_TT ${CMAKE_BINARY_DIR}/cli_tables)
add_test(NAME cli_gen COMMAND helpmate gen KQvk --tables ${CLI_TT})
add_test(NAME cli_probe COMMAND helpmate probe "8/7k/5K2/8/8/8/8/6Q1 b - - 0 1" --tables ${CLI_TT})
add_test(NAME cli_line COMMAND helpmate line "8/7k/5K2/8/8/8/8/6Q1 b - - 0 1" --tables ${CLI_TT})
add_test(NAME cli_stats COMMAND helpmate stats KQvk --tables ${CLI_TT})
add_test(NAME cli_mine COMMAND helpmate mine KQvk --dtm 2 --count 1 --max 3 --tables ${CLI_TT})
add_test(NAME cli_missing COMMAND helpmate probe "8/8/8/8/3n4/4k3/8/4K3 w - - 0 1" --tables ${CLI_TT})
add_test(NAME cli_badfen COMMAND helpmate probe "garbage" --tables ${CLI_TT})
set_tests_properties(cli_probe PROPERTIES PASS_REGULAR_EXPRESSION "dtm=2 .*h#1.*count=1" DEPENDS cli_gen)
set_tests_properties(cli_line  PROPERTIES PASS_REGULAR_EXPRESSION "Kh8 Qg7#" DEPENDS cli_gen)
set_tests_properties(cli_stats PROPERTIES PASS_REGULAR_EXPRESSION "max_dtm" DEPENDS cli_gen)
set_tests_properties(cli_mine  PROPERTIES PASS_REGULAR_EXPRESSION "b - - 0 1" DEPENDS cli_gen)
set_tests_properties(cli_missing PROPERTIES PASS_REGULAR_EXPRESSION "helpmate gen" DEPENDS cli_gen)
set_tests_properties(cli_badfen PROPERTIES PASS_REGULAR_EXPRESSION "error")
```
(`cli_missing`/`cli_badfen` exit non-zero by design; `PASS_REGULAR_EXPRESSION` makes CTest judge them by their stderr message instead of the exit code — the assertion that matters is the actionable message.)

- [ ] **Step 2: Run to verify failure** — `make test` (no `helpmate` target yet → configure error, then missing behaviors).

- [ ] **Step 3: Implement `main.cpp`**

Hand-rolled parsing, ~150 lines:
```cpp
int main(int argc, char** argv) {
    std::vector<std::string> args(argv + 1, argv + argc);
    if (args.empty()) { usage(); return 3; }
    std::string cmd = args[0];
    std::string tables = "tables"; int threads = 1, dtm = -1, count = -1, maxn = 10;
    bool all = false;
    std::vector<std::string> pos;                     // positional args
    for (size_t i = 1; i < args.size(); ++i) {        // --tables --threads --dtm --count --max --all
        if      (args[i] == "--tables"  && i + 1 < args.size()) tables  = args[++i];
        else if (args[i] == "--threads" && i + 1 < args.size()) threads = std::stoi(args[++i]);
        else if (args[i] == "--dtm"     && i + 1 < args.size()) dtm     = std::stoi(args[++i]);
        else if (args[i] == "--count"   && i + 1 < args.size()) count   = std::stoi(args[++i]);
        else if (args[i] == "--max"     && i + 1 < args.size()) maxn    = std::stoi(args[++i]);
        else if (args[i] == "--all") all = true;
        else pos.push_back(args[i]);
    }
    try {
        if (cmd == "gen")   { /* Material::parse(pos[0]) or exit 3; generate; print written files + per-slice max_dtm */ }
        if (cmd == "probe") { /* Tablebase(tables).probe(pos[0]):
                                 "dtm=2 (h#1) count=1"  |  "dtm=2 (h#1, colors flipped) count=1"  |  "unsolvable" */ }
        if (cmd == "line")  { /* line() or lines() joined with spaces, one line per solution */ }
        if (cmd == "stats") { /* print stats_json(material) */ }
        if (cmd == "mine")  { /* require --dtm; print up to maxn FENs, one per line */ }
        usage(); return 3;
    } catch (const hm::MissingTableError& e) {
        std::cerr << e.what() << "\nrun: helpmate gen <MATERIAL> --tables " << tables << "\n"; return 2;
    } catch (const std::exception& e) { std::cerr << "error: " << e.what() << "\n"; return 3; }
}
```
Each `/* ... */` is straight calls into Task 15's API with the exact output formats shown in the ctest regexes.

- [ ] **Step 4: Run tests** — `make test`, all `cli_*` cases PASS.
- [ ] **Step 5: Commit** — `git add src/cli CMakeLists.txt && git commit -m "feat: helpmate CLI (gen/probe/line/stats/mine)"`

---

### Task 17: Python bindings and packaging

**Files:**
- Create: `src/bindings/pymodule.cpp`, `python/helpmate/__init__.py`, `pyproject.toml`, `tests/python/test_smoke.py`
- Modify: `CMakeLists.txt` (guarded pybind11 section)

**Interfaces:**
- Produces the Python API:

```python
import helpmate
helpmate.generate("KQvk", tables="tables/", threads=4)   # -> list of written file paths
tb = helpmate.Tablebase("tables/")
tb.probe(fen)            # -> (dtm, count, flipped) | None if unsolvable; raises on bad FEN / missing table
tb.line(fen)             # -> list[str] SAN
tb.lines(fen, max=100)   # -> list[list[str]]
tb.mine("KQvk", dtm=2, count=1, max=100)   # -> list[str] FENs (count=-1 -> any)
tb.stats("KQvk")         # -> dict (parsed sidecar JSON)
```

- [ ] **Step 1: Write the failing test**

`tests/python/test_smoke.py`:
```python
import json, pathlib, pytest
import helpmate

@pytest.fixture(scope="session")
def tables(tmp_path_factory):
    d = str(tmp_path_factory.mktemp("tables"))
    written = helpmate.generate("KQvk", tables=d, threads=2)
    assert any(w.endswith("KQvk.hm") for w in written)
    return d

def test_probe_golden(tables):
    tb = helpmate.Tablebase(tables)
    assert tb.probe("8/7k/5K2/8/8/8/8/6Q1 b - - 0 1") == (2, 1, False)
    assert tb.probe("8/8/8/8/8/4k3/8/4K3 w - - 0 1") is None      # Kvk unsolvable

def test_line_and_mine(tables):
    tb = helpmate.Tablebase(tables)
    assert tb.line("8/7k/5K2/8/8/8/8/6Q1 b - - 0 1") == ["Kh8", "Qg7#"]
    fens = tb.mine("KQvk", dtm=2, count=1, max=5)
    assert len(fens) == 5
    for f in fens:
        assert tb.probe(f) == (2, 1, False)

def test_stats_dict(tables):
    tb = helpmate.Tablebase(tables)
    s = tb.stats("KQvk")
    assert s["material"] == "KQvk"
    assert s["max_dtm"] >= 3

def test_errors(tables):
    tb = helpmate.Tablebase(tables)
    with pytest.raises(ValueError):
        tb.probe("garbage")
    with pytest.raises(RuntimeError):
        tb.probe("8/8/8/8/3n4/4k3/8/4K3 w - - 0 1")   # Kvkn not generated
```

- [ ] **Step 2: Write packaging + bindings**

`pyproject.toml`:
```toml
[build-system]
requires = ["scikit-build-core>=0.9", "pybind11>=2.12"]
build-backend = "scikit_build_core.build"

[project]
name = "helpmate"
version = "0.1.0"
description = "Helpmate tablebases: cooperative mate distances and solution counts"
requires-python = ">=3.9"
license = {file = "LICENSE"}

[project.optional-dependencies]
dev = ["pytest", "chess>=1.10"]

[tool.scikit-build]
cmake.version = ">=3.24"
wheel.packages = ["python/helpmate"]
cmake.args = ["-DHELPMATE_PYTHON=ON"]
```

`CMakeLists.txt` addition:
```cmake
option(HELPMATE_PYTHON "build python module" OFF)
if(HELPMATE_PYTHON)
  find_package(pybind11 CONFIG REQUIRED)
  pybind11_add_module(_helpmate src/bindings/pymodule.cpp)
  target_link_libraries(_helpmate PRIVATE helpmate_core)
  install(TARGETS _helpmate DESTINATION helpmate)
endif()
```

`src/bindings/pymodule.cpp`:
```cpp
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include "probe/tablebase.h"
#include "generator/generator.h"
#include "indexing/material.h"
namespace py = pybind11;
using namespace hm;
static Material mat_or_throw(const std::string& s) {
    auto m = Material::parse(s);
    if (!m) throw std::invalid_argument("bad material string: " + s);
    return *m;
}
PYBIND11_MODULE(_helpmate, mod) {
    py::register_exception<MissingTableError>(mod, "MissingTableError", PyExc_RuntimeError);
    mod.def("generate", [](const std::string& mat, const std::string& tables, int threads) {
        GenOptions o; o.tables_dir = tables; o.threads = threads;
        return generate(mat_or_throw(mat), o);
    }, py::arg("material"), py::arg("tables") = "tables", py::arg("threads") = 1);
    py::class_<Tablebase>(mod, "Tablebase")
        .def(py::init<std::string>())
        .def("probe", [](const Tablebase& t, const std::string& fen) -> py::object {
            auto p = t.probe(fen);
            if (!p) return py::none();
            return py::make_tuple(p->dtm, p->count, p->flipped);
        })
        .def("line", &Tablebase::line)
        .def("lines", &Tablebase::lines, py::arg("fen"), py::arg("max") = 100)
        .def("mine", [](const Tablebase& t, const std::string& mat, int dtm, int count, int max) {
            std::vector<std::string> out;
            t.mine(mat_or_throw(mat), dtm, count, [&](const std::string& f) {
                out.push_back(f); return (int)out.size() < max; });
            return out;
        }, py::arg("material"), py::arg("dtm"), py::arg("count") = -1, py::arg("max") = 100)
        .def("_stats_json", [](const Tablebase& t, const std::string& mat) {
            return t.stats_json(mat_or_throw(mat)); });
}
```

`python/helpmate/__init__.py`:
```python
import json as _json
from ._helpmate import Tablebase as _Tablebase, generate, MissingTableError

class Tablebase(_Tablebase):
    def stats(self, material: str) -> dict:
        return _json.loads(self._stats_json(material))

__all__ = ["Tablebase", "generate", "MissingTableError"]
```

- [ ] **Step 3: Install and run**

```bash
pip install -e ".[dev]"
python -m pytest tests/python/test_smoke.py -v
```
Expected: all PASS. (`std::invalid_argument` maps to Python `ValueError` automatically; `MissingTableError` is registered as a `RuntimeError` subclass.)

- [ ] **Step 4: Confirm C++ suite still green** — `make test`.
- [ ] **Step 5: Commit** — `git add pyproject.toml src/bindings python tests/python/test_smoke.py CMakeLists.txt && git commit -m "feat: pybind11 bindings and pip packaging"`

---

### Task 18: python-chess cross-validation suite

**Files:**
- Create: `tests/python/test_crosscheck.py`, `tests/python/conftest.py`
- Modify: `src/bindings/pymodule.cpp` (debug helpers `_perft`, `_legal_moves`)

**Interfaces:**
- Consumes: pip package `chess` (python-chess) as the fully independent reference.
- Produces: `helpmate._helpmate._perft(fen, depth) -> int` and `_legal_moves(fen) -> list[str]` (UCI), test-only exports.

- [ ] **Step 1: Add the debug bindings**

In `pymodule.cpp`:
```cpp
    mod.def("_perft", [](const std::string& fen, int depth) {
        auto b = Board::from_fen(fen);
        if (!b) throw std::invalid_argument("bad fen");
        return b->perft(depth);
    });
    mod.def("_legal_moves", [](const std::string& fen) {
        auto b = Board::from_fen(fen);
        if (!b) throw std::invalid_argument("bad fen");
        std::vector<std::string> out;
        for (auto& m : b->legal_moves()) out.push_back(m.uci());
        return out;
    });
```

- [ ] **Step 2: Write the cross-validation tests**

`tests/python/conftest.py`:
```python
import pytest
def pytest_addoption(parser):
    parser.addoption("--run-slow", action="store_true", default=False)
def pytest_collection_modifyitems(config, items):
    if config.getoption("--run-slow"):
        return
    skip = pytest.mark.skip(reason="needs --run-slow")
    for item in items:
        if "slow" in item.keywords:
            item.add_marker(skip)
```

`tests/python/test_crosscheck.py`:
```python
import random, itertools, pytest, chess
from helpmate import _helpmate as core
import helpmate

PIECES = [chess.QUEEN, chess.ROOK, chess.BISHOP, chess.KNIGHT, chess.PAWN]

def random_position(rng, n_extra):
    """Random legal castling-free position with 2 kings + n_extra pieces."""
    while True:
        squares = rng.sample(range(64), 2 + n_extra)
        board = chess.Board(None)
        board.set_piece_at(squares[0], chess.Piece(chess.KING, chess.WHITE))
        board.set_piece_at(squares[1], chess.Piece(chess.KING, chess.BLACK))
        for sq in squares[2:]:
            pt = rng.choice(PIECES)
            if pt == chess.PAWN and not (8 <= sq < 56):
                break
            board.set_piece_at(sq, chess.Piece(pt, rng.choice([chess.WHITE, chess.BLACK])))
        else:
            board.turn = rng.choice([chess.WHITE, chess.BLACK])
            if board.is_valid():
                return board
def test_movegen_matches_python_chess():
    rng = random.Random(1234)
    for _ in range(200):
        board = random_position(rng, rng.randint(1, 5))
        fen = board.fen()
        ours = sorted(core._legal_moves(fen))
        ref = sorted(m.uci() for m in board.legal_moves)
        assert ours == ref, fen
def test_perft_matches_python_chess():
    def ref_perft(board, d):
        if d == 0: return 1
        return sum(ref_perft_after(board, m, d) for m in board.legal_moves)
    def ref_perft_after(board, m, d):
        board.push(m); n = ref_perft(board, d - 1); board.pop(); return n
    rng = random.Random(99)
    for _ in range(25):
        board = random_position(rng, rng.randint(1, 4))
        assert core._perft(board.fen(), 3) == ref_perft(board, 3), board.fen()

@pytest.mark.slow
def test_exhaustive_kqvk(tmp_path):
    """Full independent BFS of KQvk with python-chess vs every probe value."""
    tables = str(tmp_path / "t")
    helpmate.generate("KQvk", tables=tables)
    tb = helpmate.Tablebase(tables)
    # enumerate all placements: wK, bK, wQ on distinct squares, both stm
    def positions():
        for wk, bk, q in itertools.permutations(range(64), 3):
            if chess.square_distance(wk, bk) <= 1: continue
            b = chess.Board(None)
            b.set_piece_at(wk, chess.Piece(chess.KING, chess.WHITE))
            b.set_piece_at(bk, chess.Piece(chess.KING, chess.BLACK))
            b.set_piece_at(q, chess.Piece(chess.QUEEN, chess.WHITE))
            for turn in (chess.WHITE, chess.BLACK):
                b.turn = turn
                if b.is_valid(): yield b.fen()
    # forward-scan BFS in pure python-chess (independent of all our code)
    dtm = {}
    fens = list(positions())
    boards = {f: chess.Board(f) for f in fens}
    for f, b in boards.items():
        if b.turn == chess.BLACK and b.is_checkmate(): dtm[f] = 0
    d = 0
    changed = True
    while changed:
        d += 1; changed = False
        mover = chess.WHITE if d % 2 else chess.BLACK
        for f, b in boards.items():
            if f in dtm or b.turn != mover: continue
            for m in b.legal_moves:
                b.push(m); succ = b.fen(); b.pop()
                # captures leave KQvk -> Kvk or KvK-with-Q-captured: all unsolvable, skip
                if succ in dtm and dtm[succ] == d - 1:
                    dtm[f] = d; changed = True; break
    for f in fens:
        p = tb.probe(f)
        assert (p[0] if p else None) == dtm.get(f), f
```
Note for the exhaustive test: KQvk successors after a capture are Kvk positions (black king takes the queen) — unsolvable, so ignoring cross-slice successors is *provably* safe for this material and keeps the reference implementation fully independent.

- [ ] **Step 3: Run** — `python -m pytest tests/python -v` (fast set) and once `python -m pytest tests/python --run-slow -v` (KQvk exhaustive, expect several minutes). All PASS.
- [ ] **Step 4: Commit** — `git add tests/python src/bindings/pymodule.cpp && git commit -m "test: python-chess cross-validation incl. exhaustive KQvk"`

---

### Task 19: Coverage, README, finish

**Files:**
- Modify: `CMakeLists.txt` (coverage option), `Makefile` (coverage target), `README.md`

- [ ] **Step 1: Coverage wiring**

`CMakeLists.txt`:
```cmake
option(HELPMATE_COVERAGE "coverage instrumentation" OFF)
if(HELPMATE_COVERAGE)
  target_compile_options(helpmate_core PRIVATE --coverage -O0 -g)
  target_link_options(helpmate_core PUBLIC --coverage)
endif()
```
`Makefile`:
```make
coverage:
	cmake -S . -B build-cov -DHELPMATE_COVERAGE=ON -DCMAKE_BUILD_TYPE=Debug
	cmake --build build-cov -j
	ctest --test-dir build-cov --output-on-failure
	lcov --capture --directory build-cov --output-file build-cov/cov.info \
	     --include '*/src/*' --exclude '*/build*/_deps/*'
	genhtml build-cov/cov.info --output-directory build-cov/html
	lcov --summary build-cov/cov.info
```

- [ ] **Step 2: Run and check the number**

Run: `make coverage`
Expected: line coverage ≥ 80 % on `src/`. If below: add targeted unit tests for the uncovered branches (typically error paths in `table_file.cpp`, `material.cpp` parse errors, CLI arg handling) until ≥ 80 %.

- [ ] **Step 3: README**

Replace `README.md` with: what the project is (2 paragraphs, link the spec), build instructions (`make test`), CLI examples (the five commands with real output), Python quickstart (the Task 17 API), table format one-liner + pointer to `src/format/table_file.h`, and the "validated against python-chess and an independent oracle" testing story.

- [ ] **Step 4: Full suite green**

Run: `make test && python -m pytest tests/python -v && make coverage`
Expected: everything passes, coverage ≥ 80 %.

- [ ] **Step 5: Commit**

```bash
git add CMakeLists.txt Makefile README.md
git commit -m "chore: coverage target (>=80%) and user documentation"
```

---

## Execution notes

- **Task order is strict** up to Task 8; afterwards 12–14 depend on 10, 15 on 10+12, 16 on 15, 17 on 16 (packaging reuses CLI-verified behavior), 18 on 17, 19 last.
- **Performance guardrail** (not a task, a watchpoint): if KQvk generation takes > 30 s single-threaded, profile before proceeding — the likely culprit is `Board::reset` or `pieces()`/`encode` churn in the inner loop; fix inside the adapter/SliceGen without changing any interface.
- **Upstream policy**: any ChessMG bug found by Task 2/18 tests is fixed in osick/ChessMG (user's repo), then the pin in `CMakeLists.txt` is bumped — do not patch vendored files locally. STOP and ask the user before changing the pin.

