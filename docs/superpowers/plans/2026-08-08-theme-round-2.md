# Theme detection round 2 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add seven boolean themes — `homebase`, `set-play`, `kniest`, `zajic`, `phoenix`, `schnoebelen`, `pendulum` — and the `ThemeInput`/`needs` signature change that lets two of them exist and lets non-enumerating themes answer on saturated positions.

**Architecture:** A detector becomes `bool(const ThemeInput&)` where `ThemeInput` carries the diagram, the sibling side-to-move plane's value, and the solutions. The caller fetches; detectors stay pure and testable with no `.hm` on disk. Each `ThemeDef` declares `needs` (Position / Plane / Solutions), and `mine` enumerates only when some requested theme needs it. The existing sixteen detectors keep their bodies and are registered through an `any_of<>` wrapper.

**Tech Stack:** C++20 (GCC 13), Catch2 + ctest, pybind11 bindings, FastAPI, plain ES modules.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-08-08-theme-round-2-design.md`. Read it before Task 1.
- Every build and test command runs under `taskset -c 0-3`. Never more than 4 cores.
- **Never** run bare `./build/helpmate_tests` — it adds a 30–60 minute `[slow]` lane. Always `"~[slow]"` or a specific tag.
- Never write to `~/tb` or `~/tb/raw`. Reading is fine. Scratch goes in `$(mktemp -d)`.
- Never delete `build/_deps`. Configure with `taskset -c 0-3 cmake -S . -B build`.
- `make format-check` must be green before every commit. `make format` refuses a dirty tree; stage first (`git add -A`) then run `git clang-format -q`.
- Definitions are this project's own and are **not** validated against published problems. Do not silently "correct" a definition in the spec — if it looks wrong, stop and say so.
- Detectors must remain pure: no table access, no I/O, no globals. The caller supplies values.
- Commit trailer: `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`
- **Fixture rule, from the v0.8 post-mortem: twenty hand-authored fixtures were wrong.** Every fixture must be built with the `play()` helper in `src/core/tests/test_line_themes.cpp`, which `REQUIRE`s each move is legal — a wrong fixture then fails loudly instead of passing vacuously. Never assert a board state you typed; assert one the engine produced.

  **This plan deliberately supplies no fixture FENs.** A FEN typed into a plan
  is exactly as unreliable as one typed into a test, and eight of the twenty
  bad v0.8 fixtures descended from a single skeleton whose kings were
  diagonally adjacent — illegal, never mate, and every test built on it passed
  vacuously. Construct each fixture with this procedure instead:

  1. Write the position you intend, then **check it is legal and is what you
     think** before using it:
     `taskset -c 0-3 ./build/helpmate probe "<FEN>" --tables $TT`
     A position that does not parse, or is not solvable when you expected a
     mate in *n*, is wrong — fix it now, not after the test goes green.
  2. Build the solution with `play()`, which rejects an illegal move.
  3. **Assert the fixture's shape before asserting the detector.** Every
     positive test must first `REQUIRE` the facts the theme depends on — that
     the intended ply really captured, that the mate really is mate — so a
     fixture that drifts fails on the `REQUIRE`, not silently on the `CHECK`.
     Each task below names the exact shape assertions for its theme.
  4. `$TT` is a scratch table dir: `TT=$(mktemp -d) && taskset -c 0-3 ./build/helpmate gen KQvk --tables $TT`. Never `~/tb`.
- **Mutation rule, from the same post-mortem: three detector branches survived deletion and two survived inversion with the suite green.** For each new detector, delete its central condition and run the tests, then invert it and run again. Both must fail. Record in the commit that you did it.

---

### Task 1: `ThemeInput`, `Needs`, and one assembly point

Pure refactor. Zero behaviour change — that is the acceptance criterion.

**Files:**
- Modify: `src/core/themes/registry.h`
- Modify: `src/core/themes/registry.cpp`
- Modify: `src/core/probe/tablebase.h`, `src/core/probe/tablebase.cpp`
- Modify: `src/packages/bindings/pymodule.cpp`
- Modify: `src/packages/cli/main.cpp`
- Test: `src/core/tests/test_themes_registry.cpp`

**Interfaces:**
- Produces: `hm::themes::Needs{Position,Plane,Solutions}`; `hm::themes::ThemeInput{const Board& start; std::optional<ValuePair> other_plane; const std::vector<Solution>& solutions;}`; `using Detector = bool (*)(const ThemeInput&)`; `ThemeDef{name, fn, doc, needs}`; `template <bool (*F)(const Solution&)> bool any_of(const ThemeInput&)`; `std::vector<std::string> detect(const ThemeInput&)`; `std::vector<std::string> Tablebase::themes_of(const std::string& fen, int max) const`.

- [ ] **Step 1: Write the failing test**

Append to `src/core/tests/test_themes_registry.cpp`:

```cpp
TEST_CASE("every entry declares what input it needs", "[themes][registry]") {
    for (const auto& t : theme_registry()) REQUIRE(t.needs == Needs::Solutions);
}

TEST_CASE("any_of gives the same answer detect() used to give", "[themes][registry]") {
    // Two solutions, only the second promoting: `any` must find it.
    auto b = Board::from_fen("8/P6k/8/8/8/8/8/K7 w - - 0 1");
    REQUIRE(b);
    std::vector<Solution> sols{Solution{*b, {}}, Solution{*b, {}}};
    ThemeInput in{*b, std::nullopt, sols};
    auto names = detect(in);
    REQUIRE(std::find(names.begin(), names.end(), "promotion") == names.end());
}
```

- [ ] **Step 2: Run it and watch it fail to compile**

```bash
taskset -c 0-3 cmake --build build -j4 2>&1 | grep -E "error" | head
```
Expected: errors on `t.needs`, `Needs`, `ThemeInput`.

- [ ] **Step 3: Change the registry interface**

In `src/core/themes/registry.h`, replace the `Detector`/`ThemeDef`/`detect` block:

```cpp
// What a detector must be given. Ordered by cost: a query needs only the
// most expensive input any of its themes asks for.
enum class Needs : uint8_t { Position = 0, Plane = 1, Solutions = 2 };

// Everything a detector may read. The CALLER fetches; the detector stays a
// pure function, so it is still testable against a hand-built position with
// no .hm file on disk. `solutions` is empty unless some theme needs it, and
// `other_plane` is nullopt unless some theme needs it.
struct ThemeInput {
    const Board& start;
    std::optional<ValuePair> other_plane;
    const std::vector<Solution>& solutions;
};

using Detector = bool (*)(const ThemeInput&);

struct ThemeDef {
    std::string_view name;
    Detector fn;
    std::string_view doc;
    Needs needs;
};

// Adapts a per-solution detector to the registry signature, supplying the
// `any` the query surface uses. This is the ONLY place `any` is expressed.
template <bool (*F)(const Solution&)>
bool any_of(const ThemeInput& in) {
    for (const auto& s : in.solutions)
        if (F(s)) return true;
    return false;
}

const std::vector<ThemeDef>& theme_registry();
const ThemeDef* find_theme(std::string_view name);
std::vector<std::string> detect(const ThemeInput& in);
```

Add `#include <optional>` and `#include "chess/types.h"` at the top.

- [ ] **Step 4: Wrap the sixteen existing entries**

In `src/core/themes/registry.cpp`, every entry becomes `{"name", &any_of<&fn>, "doc", Needs::Solutions}`. For example:

```cpp
{"pure", &any_of<&is_pure>,
 "Pure mate: every square of the black king's field is unavailable for "
 "exactly one reason, and the king's square is attacked exactly once "
 "(so double check is impure).",
 Needs::Solutions},
```

Do this for all sixteen. Then rewrite `detect`:

```cpp
std::vector<std::string> detect(const ThemeInput& in) {
    std::vector<std::string> out;
    for (const auto& t : theme_registry())
        if (t.fn(in)) out.emplace_back(t.name);
    return out;
}
```

- [ ] **Step 5: Add the single assembly point**

The v0.8 review found each surface assembling theme inputs separately and so
able to diverge. One method now owns it. In `src/core/probe/tablebase.h`, in
the public section:

```cpp
    // Theme names this position shows. THE one place a ThemeInput is built:
    // CLI, bindings and API all route here, so they cannot drift apart.
    // `max` caps enumeration; -1 means "this position's own solution count".
    std::vector<std::string> themes_of(const std::string& fen, int max) const;
```

In `src/core/probe/tablebase.cpp`:

```cpp
std::vector<std::string> Tablebase::themes_of(const std::string& fen, int max) const {
    auto b = Board::from_fen(fen);
    if (!b) throw std::invalid_argument("bad FEN (or castling rights): " + fen);
    std::vector<Solution> sols = solutions(fen, max);
    themes::ThemeInput in{*b, std::nullopt, sols};
    return themes::detect(in);
}
```

- [ ] **Step 6: Point the callers at it**

In `src/packages/bindings/pymodule.cpp`, replace `themes::detect(t.solutions(fen, max))` with `t.themes_of(fen, max)`. In `src/packages/cli/main.cpp`, replace the equivalent call in `cmd_probe`'s `--themes` path with `tb.themes_of(fen, max)`. Leave every comment explaining the `max` semantics in place.

- [ ] **Step 7: Build and run the theme suites**

```bash
taskset -c 0-3 cmake --build build -j4 2>&1 | grep -E " error" | head
taskset -c 0-3 ./build/helpmate_tests "[themes]" 2>&1 | tail -3
```
Expected: PASS.

- [ ] **Step 8: Prove zero behaviour change on a real table**

This is the acceptance criterion for the whole task. `~/tb` is read-only.

```bash
for t in pure model ideal mirror promotion underpromotion excelsior excelsior:white \
         excelsior:black switchback closed-walk self-block single-piece \
         single-piece:white single-piece:black en-passant; do
  n=$(taskset -c 0-3 ./build/helpmate mine KRvkbn --dtm 8 --theme "$t" --max 200 --tables ~/tb 2>/dev/null | md5sum | cut -c1-10)
  printf '%-22s %s\n' "$t" "$n"
done | tee /tmp/after.txt
```
Compare against the same run from `git stash`-ed HEAD. Every one of the
sixteen must be byte-identical. If any differs, stop — the refactor is wrong.

- [ ] **Step 9: Gate and commit**

```bash
taskset -c 0-3 make format-check && taskset -c 0-3 ctest --test-dir build 2>&1 | grep "tests passed"
git add -A && git clang-format -q && git add -A
git commit -m "refactor: detectors take a ThemeInput, and declare what they need

Detectors become bool(const ThemeInput&), carrying the diagram, the sibling
side-to-move plane's value and the solutions. The caller fetches; detectors
stay pure and testable with no .hm on disk. The sixteen existing detectors
keep their bodies and are registered through any_of<>, which is now the only
place the \`any\` across solutions is expressed -- it previously lived in both
detect() and mine.

Tablebase::themes_of() becomes the single place a ThemeInput is assembled, so
CLI, bindings and API cannot drift apart the way the v0.8 review found them
able to.

Verified byte-identical mine output for all sixteen themes on a real KRvkbn
table before and after.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: `homebase` — the first Position-only theme

**Files:**
- Create: `src/core/themes/position_themes.h`, `src/core/themes/position_themes.cpp`
- Modify: `src/core/themes/registry.cpp`, `src/core/CMakeLists.txt`
- Test: `src/core/tests/test_position_themes.cpp` (create), `src/core/CMakeLists.txt`

**Interfaces:**
- Consumes: `ThemeInput`, `Needs` from Task 1.
- Produces: `bool hm::themes::is_homebase(const ThemeInput&)`.

- [ ] **Step 1: Write the failing test**

Create `src/core/tests/test_position_themes.cpp`:

```cpp
#include <catch2/catch_test_macros.hpp>

#include "themes/position_themes.h"
#include "themes/registry.h"

using namespace hm;
using namespace hm::themes;

static bool homebase(const std::string& fen) {
    auto b = Board::from_fen(fen);
    REQUIRE(b);
    std::vector<Solution> none;
    ThemeInput in{*b, std::nullopt, none};
    return is_homebase(in);
}

TEST_CASE("homebase: bare kings on their own squares", "[themes][position]") {
    CHECK(homebase("4k3/8/8/8/8/8/8/4K3 b - - 0 1"));
}

TEST_CASE("homebase: a king off its square breaks it", "[themes][position]") {
    CHECK_FALSE(homebase("4k3/8/8/8/8/8/8/3K4 b - - 0 1"));
}

TEST_CASE("homebase: officers on their game-array squares", "[themes][position]") {
    CHECK(homebase("4k3/8/8/8/8/8/8/R3K2R b - - 0 1"));
    CHECK(homebase("1n2k3/8/8/8/8/8/8/2B1K3 b - - 0 1"));
}

TEST_CASE("homebase: a pawn anywhere on its home rank counts", "[themes][position]") {
    // Deliberate spec decision: requiring the pawn's OWN file would make the
    // theme useless. A white pawn on d2 and a black pawn on f7 are both home,
    // even though neither stands on a d- or f-pawn's game-array file only by
    // coincidence -- rank is the whole test.
    CHECK(homebase("4k3/8/8/8/8/8/3P4/4K3 b - - 0 1"));
    CHECK(homebase("4k3/5p2/8/8/8/8/8/4K3 b - - 0 1"));
}

TEST_CASE("homebase: a black pawn on rank 7 counts, on rank 6 does not", "[themes][position]") {
    CHECK(homebase("4k3/3p4/8/8/8/8/8/4K3 b - - 0 1"));
    CHECK_FALSE(homebase("4k3/8/3p4/8/8/8/8/4K3 b - - 0 1"));
}

TEST_CASE("homebase: a queen on the wrong colour's square breaks it", "[themes][position]") {
    CHECK(homebase("3qk3/8/8/8/8/8/8/3QK3 b - - 0 1"));
    CHECK_FALSE(homebase("4k3/8/8/8/8/8/8/4KQ2 b - - 0 1"));
}

TEST_CASE("homebase is registered and needs only the position", "[themes][registry]") {
    const auto* t = find_theme("homebase");
    REQUIRE(t != nullptr);
    REQUIRE(t->needs == Needs::Position);
}
```

- [ ] **Step 2: Run it and watch it fail**

```bash
taskset -c 0-3 cmake -S . -B build >/dev/null && taskset -c 0-3 cmake --build build -j4 2>&1 | grep -E " error" | head
```
Expected: `position_themes.h` not found.

- [ ] **Step 3: Implement**

`src/core/themes/position_themes.h`:

```cpp
#pragma once
#include "themes/registry.h"

namespace hm::themes {

// Detectors that read the DIAGRAM only -- no solutions, no table. These are
// the themes a query can answer without enumerating, which also makes them
// the only themes that can answer on a saturated position.

// Every unit stands on a square it occupies in the initial game array for its
// own colour and type. Pawns count anywhere on their home rank: requiring the
// file would make the theme useless, and the sense of the name is "nothing has
// left home yet".
bool is_homebase(const ThemeInput& in);

}  // namespace hm::themes
```

`src/core/themes/position_themes.cpp`:

```cpp
#include "themes/position_themes.h"

namespace hm::themes {

namespace {
// Home squares by piece type for White; Black's are the same files on rank 8.
bool on_home_square(Piece p, int sq) {
    const int file = sq_file(sq), rank = sq_rank(sq);
    const int back = p.color == Color::White ? 0 : 7;
    const int pawn_rank = p.color == Color::White ? 1 : 6;
    switch (p.type) {
        case PieceType::Pawn: return rank == pawn_rank;
        case PieceType::King: return rank == back && file == 4;
        case PieceType::Queen: return rank == back && file == 3;
        case PieceType::Rook: return rank == back && (file == 0 || file == 7);
        case PieceType::Bishop: return rank == back && (file == 2 || file == 5);
        case PieceType::Knight: return rank == back && (file == 1 || file == 6);
    }
    return false;
}
}  // namespace

bool is_homebase(const ThemeInput& in) {
    for (const auto& pp : in.start.pieces())
        if (!on_home_square(pp.piece, pp.square)) return false;
    return true;
}

}  // namespace hm::themes
```

Add `themes/position_themes.cpp` to the core library sources in `src/core/CMakeLists.txt`, and `tests/test_position_themes.cpp` to the test sources, following the lines that already list `themes/line_themes.cpp` and `tests/test_line_themes.cpp`.

Register it in `src/core/themes/registry.cpp` (add `#include "themes/position_themes.h"`), as the first entry so it leads the list:

```cpp
{"homebase", &is_homebase,
 "Homebase: every unit stands on a square it occupies in the initial game "
 "array for its own colour and type. Pawns count anywhere on their home "
 "rank.",
 Needs::Position},
```

Update the registry-size test in `test_themes_registry.cpp` from 16 to 17, and relax the "every entry declares what input it needs" test written in Task 1 to `REQUIRE(t.needs <= Needs::Solutions)`.

- [ ] **Step 4: Run the tests**

```bash
taskset -c 0-3 cmake --build build -j4 2>&1 | grep -E " error" | head
taskset -c 0-3 ./build/helpmate_tests "[themes]" 2>&1 | tail -3
```
Expected: PASS.

- [ ] **Step 5: Mutation-check the detector**

Change `if (!on_home_square(...)) return false;` to `return true;` — run the tests, they MUST fail. Then invert to `if (on_home_square(...)) return false;` — run again, they MUST fail. Restore. If either survives, the tests are too weak; add a case that kills it.

- [ ] **Step 6: Gate and commit**

```bash
taskset -c 0-3 make format-check && taskset -c 0-3 ./build/helpmate_tests "~[slow]" 2>&1 | tail -2
git add -A && git clang-format -q && git add -A
git commit -m "feat(themes): homebase, the first theme needing only the diagram

Every unit stands on a game-array square for its own colour and type. Pawns
count anywhere on their home rank -- requiring the file would make the theme
useless, and the sense of the name is that nothing has left home yet.

Declared Needs::Position, so once mine honours \`needs\` (next task) this
theme answers without enumerating, including on saturated positions where
every existing theme gives up.

Detector mutation-checked: deleting and inverting its central condition each
fail the suite.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: `mine` honours `needs`

The user-visible payoff. A query whose themes are all Position-only stops enumerating and stops skipping saturated positions.

**Files:**
- Modify: `src/core/probe/tablebase.cpp` (the `mine` scan loop)
- Test: `src/core/tests/test_solutions.cpp`

**Interfaces:**
- Consumes: `Needs`, `ThemeInput`, `is_homebase` from Tasks 1–2.
- Produces: no new symbols; `mine`'s behaviour changes for Position-only theme queries.

- [ ] **Step 1: Write the failing test**

Append to `src/core/tests/test_solutions.cpp` — it already generates a fixture table; follow the `gen_dir()` idiom in that file, or in `test_probe.cpp` if `test_solutions.cpp` has none.

```cpp
TEST_CASE("a position-only theme does not enumerate, so saturation cannot hide it",
          "[themes][mine]") {
    Tablebase tb(gen_dir());
    MineFilter f;
    f.dtm = 2;
    f.themes = {"homebase"};
    uint64_t skipped = 0;
    int hits = 0;
    tb.mine(*Material::parse("KQvk"), f, [&](const std::string&) { ++hits; return hits < 50; },
            &skipped);
    // The whole point: nothing was skipped for saturation, because nothing was
    // enumerated. A solutions-needing theme on the same table does skip.
    CHECK(skipped == 0);
}
```

- [ ] **Step 2: Run it and watch it fail**

```bash
taskset -c 0-3 cmake --build build -j4 2>&1 | grep -E " error" | head
taskset -c 0-3 ./build/helpmate_tests "[mine]" 2>&1 | tail -5
```
Expected: FAIL — `skipped` is non-zero, because every theme currently enumerates.

- [ ] **Step 3: Implement**

In `src/core/probe/tablebase.cpp`, in `mine`, replace the detector-resolution block and the `want_solutions` line:

```cpp
    std::vector<themes::Detector> dets;
    themes::Needs need = themes::Needs::Position;
    for (const auto& n : f.themes) {
        const auto* d = themes::find_theme(n);
        if (!d) throw std::invalid_argument("unknown theme: \"" + n + "\"");
        dets.push_back(d->fn);
        need = std::max(need, d->needs);
    }

    const bool want_shape = f.starts >= 0 || f.ends >= 0;
    // Enumerate only when something actually needs the solutions. A query whose
    // themes read only the diagram runs at scan speed AND answers on saturated
    // positions, where enumeration is impossible and every other theme gives up.
    const bool want_solutions = want_shape || (!dets.empty() && need == themes::Needs::Solutions);
```

Then, inside the loop, replace the theme-matching block so it builds a `ThemeInput` rather than looping detectors over solutions:

```cpp
            if (!dets.empty()) {
                std::vector<Solution> sols;
                if (need == themes::Needs::Solutions) sols = solutions(fen, (int)v.count);
                Board start = Board::from_pieces(pp, stm);
                themes::ThemeInput tin{start, std::nullopt, sols};
                bool all_present = true;
                for (auto d : dets)
                    if (!d(tin)) { all_present = false; break; }
                if (!all_present) continue;
            }
```

and move the saturation guard so it only applies when solutions are wanted:

```cpp
            if (want_solutions && v.count >= COUNT_SAT) {
                if (skipped_saturated) ++*skipped_saturated;
                continue;
            }
```

- [ ] **Step 4: Run the tests**

```bash
taskset -c 0-3 ./build/helpmate_tests "[themes]" "[mine]" 2>&1 | tail -3
```
Expected: PASS.

- [ ] **Step 5: Prove the sixteen still behave, and measure the win**

```bash
for t in pure model excelsior closed-walk self-block en-passant; do
  a=$(taskset -c 0-3 ./build/helpmate mine KRvkbn --dtm 8 --theme "$t" --max 200 --tables ~/tb 2>/dev/null | md5sum | cut -c1-10)
  printf '%-14s %s\n' "$t" "$a"
done
echo "--- homebase must now be fast and must not skip ---"
taskset -c 0-3 /usr/bin/time -f "%e s" ./build/helpmate mine KRvkbn --dtm 8 --theme homebase --max 200 --tables ~/tb
taskset -c 0-3 /usr/bin/time -f "%e s" ./build/helpmate mine KRvkbn --dtm 8 --theme model --max 200 --tables ~/tb >/dev/null
```
Expected: the six hashes match Task 1's baseline; `homebase` runs at roughly plain-scan speed and prints no "skipped ... saturated" note, while `model` still does.

- [ ] **Step 6: Gate and commit**

```bash
taskset -c 0-3 make format-check && taskset -c 0-3 ctest --test-dir build 2>&1 | grep "tests passed"
git add -A && git clang-format -q && git add -A
git commit -m "feat(mine): enumerate only when a theme actually needs the solutions

mine forced enumeration for every theme, which costs ~10.7x a plain scan and
is impossible for the ~65% of 6-piece cells whose solution count saturates --
those positions were skipped and counted, so a theme query silently never saw
them. It now takes the maximum \`needs\` across the requested themes and
enumerates only for Needs::Solutions, and the saturation guard applies only
when solutions are wanted.

So --theme homebase runs at scan speed and answers on saturated positions.
That is a capability difference, not a speed-up.

Verified the sixteen solution-needing themes produce byte-identical output on
a real KRvkbn table.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: `set-play` — the Plane-only theme

**Files:**
- Modify: `src/core/themes/position_themes.h`, `src/core/themes/position_themes.cpp`
- Modify: `src/core/themes/registry.cpp`
- Modify: `src/core/probe/tablebase.cpp` (`mine` and `themes_of` supply `other_plane`)
- Test: `src/core/tests/test_position_themes.cpp`

**Interfaces:**
- Consumes: everything from Tasks 1–3.
- Produces: `bool hm::themes::has_set_play(const ThemeInput&)`.

- [ ] **Step 1: Write the failing test**

Append to `src/core/tests/test_position_themes.cpp`:

```cpp
static bool setplay(std::optional<ValuePair> other) {
    auto b = Board::from_fen("4k3/8/8/8/8/8/8/4K3 b - - 0 1");
    REQUIRE(b);
    std::vector<Solution> none;
    ThemeInput in{*b, other, none};
    return has_set_play(in);
}

TEST_CASE("set-play: the other plane being solvable is the whole definition",
          "[themes][position]") {
    CHECK(setplay(ValuePair{4, 1}));
    CHECK(setplay(ValuePair{0, 1}));
    CHECK_FALSE(setplay(ValuePair{DTM_UNSOLVABLE, 0}));
    CHECK_FALSE(setplay(ValuePair{DTM_INVALID, 0}));
    // Absent means "the caller did not fetch it" -- never guess a yes.
    CHECK_FALSE(setplay(std::nullopt));
}

TEST_CASE("set-play is registered and needs the plane", "[themes][registry]") {
    const auto* t = find_theme("set-play");
    REQUIRE(t != nullptr);
    REQUIRE(t->needs == Needs::Plane);
}
```

- [ ] **Step 2: Run it and watch it fail**

```bash
taskset -c 0-3 cmake --build build -j4 2>&1 | grep -E " error" | head
```
Expected: `has_set_play` not declared.

- [ ] **Step 3: Implement the detector**

In `position_themes.h`:

```cpp
// The same position with the OTHER side to move is solvable. Cheap for a
// reason specific to this project: a cell index is independent of side to
// move -- side to move selects the PLANE, not the index -- so this is the
// same cell in the sibling plane, one extra byte from a read the scan is
// already doing. Absent input means the caller did not fetch it, and is
// answered "no": never guess a yes.
bool has_set_play(const ThemeInput& in);
```

In `position_themes.cpp`:

```cpp
bool has_set_play(const ThemeInput& in) {
    return in.other_plane.has_value() && in.other_plane->dtm <= DTM_MAX;
}
```

Register in `registry.cpp` after `homebase`:

```cpp
{"set-play", &has_set_play,
 "Set play: the same position with the other side to move is also solvable.",
 Needs::Plane},
```

Bump the registry-size test to 18.

- [ ] **Step 4: Supply `other_plane` from both callers**

In `Tablebase::themes_of`, fetch it:

```cpp
std::vector<std::string> Tablebase::themes_of(const std::string& fen, int max) const {
    auto b = Board::from_fen(fen);
    if (!b) throw std::invalid_argument("bad FEN (or castling rights): " + fen);
    std::vector<Solution> sols = solutions(fen, max);
    std::optional<ValuePair> other;
    Board flipped = *b;
    flipped.reset(b->pieces(), b->stm() == Color::White ? Color::Black : Color::White);
    try {
        other = value_of(flipped);
    } catch (const MissingTableError&) {
        other = std::nullopt;  // no table for the sibling plane: answer "no"
    }
    themes::ThemeInput in{*b, other, sols};
    return themes::detect(in);
}
```

In `mine`, when `need >= Needs::Plane`, read the sibling plane in the same chunked pass. Add a third buffer beside `dtm_buf`/`cnt_buf` and fill it only when required:

```cpp
    const Color other_stm = stm == Color::White ? Color::Black : Color::White;
    const bool want_plane = !dets.empty() && need >= themes::Needs::Plane;
    std::vector<uint8_t> other_buf(want_plane ? kScanChunk : 0);
    ...
            s->reader.read_values(stm, chunk_base, chunk_n, dtm_buf.data(), cnt_buf.data());
            if (want_plane)
                s->reader.read_values(other_stm, chunk_base, chunk_n, other_buf.data(), nullptr);
```

and build the input with it:

```cpp
                std::optional<ValuePair> other;
                if (want_plane) other = ValuePair{other_buf[c - chunk_base], 0};
                themes::ThemeInput tin{start, other, sols};
```

- [ ] **Step 5: Run the tests**

```bash
taskset -c 0-3 cmake --build build -j4 2>&1 | grep -E " error" | head
taskset -c 0-3 ./build/helpmate_tests "[themes]" 2>&1 | tail -3
```
Expected: PASS.

- [ ] **Step 6: Cross-check against probe on a real table**

Every position `mine --theme set-play` returns must, when probed with its side
to move flipped, be solvable. Ten samples is enough to catch a plane mix-up,
which is the failure mode here:

```bash
taskset -c 0-3 ./build/helpmate mine KRvkbn --dtm 8 --theme set-play --max 10 --tables ~/tb | \
while read -r fen; do
  flip=$(echo "$fen" | awk '{ $2 = ($2=="b" ? "w" : "b"); print }')
  printf '%s -> ' "$flip"; taskset -c 0-3 ./build/helpmate probe "$flip" --tables ~/tb
done
```
Expected: every line reports a dtm, none reports unsolvable. If any is
unsolvable, the sibling-plane read is wrong.

- [ ] **Step 7: Mutation-check and commit**

Invert the comparison to `>= DTM_MAX` and run `"[themes]"` — it must fail.
Drop the `has_value()` guard and run — it must fail. Restore.

```bash
taskset -c 0-3 make format-check && taskset -c 0-3 ctest --test-dir build 2>&1 | grep "tests passed"
git add -A && git clang-format -q && git add -A
git commit -m "feat(themes): set-play, read from the sibling side-to-move plane

The same position with the other side to move is solvable. Needs::Plane, so
it answers without enumerating, including on saturated positions.

Cheap for a reason specific to this project: a cell index is independent of
side to move -- side to move selects the plane, not the index -- so mine
fetches it as the same cell in the sibling plane, one extra byte from a read
the scan already does. probe flips the side to move and looks the position up
once. Absent input is answered \"no\" rather than guessed.

Cross-checked on a real KRvkbn table: every position the filter returns is
solvable when probed with its side to move flipped.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: `kniest`

**Files:**
- Modify: `src/core/themes/line_themes.h`, `src/core/themes/line_themes.cpp`, `src/core/themes/registry.cpp`
- Test: `src/core/tests/test_line_themes.cpp`

**Interfaces:**
- Produces: `bool hm::themes::has_kniest(const Solution& s)`; registered as `any_of<&has_kniest>` with `Needs::Solutions`.

- [ ] **Step 1: Write the failing test**

Append to `src/core/tests/test_line_themes.cpp`, using the existing `play()`
helper so every move is checked legal:

Three cases. Build each fixture by the procedure in Global Constraints, and
open each positive with the shape assertions shown — they are what stops a
drifted fixture passing vacuously.

```cpp
// Helper: the black king's square on a board, or -1.
static int bk_of(const Board& b) {
    for (const auto& pp : b.pieces())
        if (pp.piece.type == PieceType::King && pp.piece.color == Color::Black)
            return pp.square;
    return -1;
}

TEST_CASE("kniest: a capture on the square the king is later mated on",
          "[themes][line]") {
    // Intended shape: some ply captures on S; the black king is mated on S.
    Solution s = play(FEN, MOVES);
    const Board& fin = final_board(s);
    REQUIRE(fin.state() == PosState::Checkmate);          // it really is mate
    const int bk = bk_of(fin);
    REQUIRE(bk >= 0);
    bool captured_on_bk = false;
    for (const auto& p : s.plies)
        if (p.captured && (int)p.to == bk) captured_on_bk = true;
    REQUIRE(captured_on_bk);                               // the fixture really shows it
    CHECK(has_kniest(s));
}

TEST_CASE("kniest: a capture elsewhere is not kniest", "[themes][line]") {
    // Intended shape: a capture happens, but not on the king's final square.
    Solution s = play(FEN, MOVES);
    const int bk = bk_of(final_board(s));
    bool any_capture = false, on_bk = false;
    for (const auto& p : s.plies) {
        if (p.captured) any_capture = true;
        if (p.captured && (int)p.to == bk) on_bk = true;
    }
    REQUIRE(any_capture);      // a fixture with no capture would pass for the wrong reason
    REQUIRE_FALSE(on_bk);
    CHECK_FALSE(has_kniest(s));
}

TEST_CASE("kniest: the king merely ending on a square is not enough", "[themes][line]") {
    // Intended shape: no capture at all.
    Solution s = play(FEN, MOVES);
    for (const auto& p : s.plies) REQUIRE_FALSE(p.captured);
    CHECK_FALSE(has_kniest(s));
}
```

- [ ] **Step 2: Run it and watch it fail**

```bash
taskset -c 0-3 cmake --build build -j4 2>&1 | grep -E " error" | head
```
Expected: `has_kniest` not declared.

- [ ] **Step 3: Implement**

In `line_themes.h`:

```cpp
// Some ply captures on square S, and in the mating position the black king
// stands on S.
bool has_kniest(const Solution& s);
```

In `line_themes.cpp`:

```cpp
bool has_kniest(const Solution& s) {
    const Board& fin = final_board(s);
    int bk = -1;
    for (const auto& pp : fin.pieces())
        if (pp.piece.type == PieceType::King && pp.piece.color == Color::Black) bk = pp.square;
    if (bk < 0) return false;
    for (const auto& p : s.plies)
        if (p.captured && (int)p.to == bk) return true;
    return false;
}
```

Note the en-passant subtlety: an ep capture takes a pawn that is NOT on `p.to`,
so `p.to == bk` is still the right test — the square the capture *lands* on is
the square in question.

Register with `Needs::Solutions`:

```cpp
{"kniest", &any_of<&has_kniest>,
 "Kniest: a unit is captured on the square where the black king is later "
 "mated.",
 Needs::Solutions},
```

Bump the registry-size test to 19.

- [ ] **Step 4: Run the tests**

```bash
taskset -c 0-3 ./build/helpmate_tests "[themes]" 2>&1 | tail -3
```
Expected: PASS.

- [ ] **Step 5: Mutation-check**

Delete the `p.captured &&` conjunct — tests must fail. Change `p.to` to
`p.from` — tests must fail. Restore.

- [ ] **Step 6: Gate and commit**

```bash
taskset -c 0-3 make format-check && taskset -c 0-3 ./build/helpmate_tests "~[slow]" 2>&1 | tail -2
git add -A && git clang-format -q && git add -A
git commit -m "feat(themes): kniest -- capture on the square the king is mated on

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: `zajic`

Same file set and the same six-step shape as Task 5.

**Files:**
- Modify: `src/core/themes/line_themes.h`, `src/core/themes/line_themes.cpp`, `src/core/themes/registry.cpp`
- Test: `src/core/tests/test_line_themes.cpp`

**Interfaces:**
- Produces: `bool hm::themes::has_zajic(const Solution& s)`.

- [ ] **Step 1: Write the failing test**

Three cases, fixtures built by the Global Constraints procedure. Reuse the
`bk_of()` helper added in Task 5. Open each with these shape assertions:

- **positive** — capture on S, the black king recaptures on S, mated on S:
  `REQUIRE(final_board(s).state() == PosState::Checkmate);`
  `REQUIRE(bk_of(final_board(s)) == sq("<S>"));` and assert two plies land on
  S with `captured`, the later one moved by the black king
  (`p.piece.type == PieceType::King && p.piece.color == Color::Black`).
- **negative, wrong recapturer** — same shape but the second capture on S is
  by a black unit that is not the king. `REQUIRE` that ply's
  `piece.type != PieceType::King`.
- **negative, wrong square** — the king recaptures on S but is mated
  elsewhere. `REQUIRE(bk_of(final_board(s)) != sq("<S>"));`

- [ ] **Step 2: Run it and watch it fail**

```bash
taskset -c 0-3 cmake --build build -j4 2>&1 | grep -E " error" | head
```

- [ ] **Step 3: Implement**

```cpp
// A unit is captured on S, a later ply recaptures on S with the black king,
// and the black king is mated standing on S.
bool has_zajic(const Solution& s) {
    const Board& fin = final_board(s);
    int bk = -1;
    for (const auto& pp : fin.pieces())
        if (pp.piece.type == PieceType::King && pp.piece.color == Color::Black) bk = pp.square;
    if (bk < 0) return false;
    for (size_t i = 0; i < s.plies.size(); ++i) {
        if (!s.plies[i].captured || (int)s.plies[i].to != bk) continue;
        for (size_t j = i + 1; j < s.plies.size(); ++j) {
            const Ply& r = s.plies[j];
            if (r.captured && (int)r.to == bk && r.piece.type == PieceType::King &&
                r.piece.color == Color::Black)
                return true;
        }
    }
    return false;
}
```

Declare it in `line_themes.h` with that comment, register with
`Needs::Solutions` and the doc `"Zajic: a unit is captured on the square where the black king is mated, and the king recaptures there."`, and bump the registry-size test to 20.

- [ ] **Step 4: Run the tests** — `taskset -c 0-3 ./build/helpmate_tests "[themes]"`, expect PASS.
- [ ] **Step 5: Mutation-check** — drop the `r.piece.color == Color::Black` conjunct (must fail); change `j = i + 1` to `j = 0` (must fail). Restore.
- [ ] **Step 6: Gate and commit** as in Task 5, message `feat(themes): zajic -- capture on the mating square, recaptured by the king`.

---

### Task 7: `phoenix`

**Files:** as Task 5.
**Interfaces:** Produces `bool hm::themes::has_phoenix(const Solution& s)`.

- [ ] **Step 1: Write the failing test**

Three cases, fixtures built by the Global Constraints procedure. Open each
with these shape assertions:

- **positive** — a black knight is captured, a black pawn later promotes to a
  knight. `REQUIRE` some ply has `captured == PieceType::Knight` and a LATER
  ply has `promotion == PieceType::Knight` with `piece.color == Color::Black`.
- **negative, wrong type** — the promotion is to a different type than the
  captured unit. `REQUIRE` the captured type and the promoted type differ.
- **negative, wrong colour** — the promoting side is the opposite colour from
  the captured unit's owner. `REQUIRE` the promoting ply's `piece.color`
  equals the capturing ply's `piece.color` (i.e. the promoter is the side that
  did the capturing, not the side that lost the unit). This is the case a
  careless implementation gets wrong, so assert the shape explicitly.

- [ ] **Step 2: Run it and watch it fail.**

- [ ] **Step 3: Implement**

```cpp
// A unit of type T belonging to side C is captured, and a LATER ply promotes
// a pawn of side C to type T -- the captured unit is reborn.
bool has_phoenix(const Solution& s) {
    for (size_t i = 0; i < s.plies.size(); ++i) {
        const Ply& cap = s.plies[i];
        if (!cap.captured) continue;
        // The captured unit belongs to the side that did NOT move.
        const Color owner = cap.piece.color == Color::White ? Color::Black : Color::White;
        for (size_t j = i + 1; j < s.plies.size(); ++j) {
            const Ply& pr = s.plies[j];
            if (pr.promotion && *pr.promotion == *cap.captured && pr.piece.color == owner)
                return true;
        }
    }
    return false;
}
```

Register with `Needs::Solutions`, doc `"Phoenix: a unit is captured and a pawn of the same colour later promotes to that same type."`, registry size 21.

- [ ] **Step 4: Run the tests.**
- [ ] **Step 5: Mutation-check** — drop `pr.piece.color == owner` (must fail); flip `owner` to `cap.piece.color` (must fail). Restore.
- [ ] **Step 6: Gate and commit**, message `feat(themes): phoenix -- a captured type reborn by promotion`.

---

### Task 8: `schnoebelen`

**Files:** as Task 5.
**Interfaces:** Produces `bool hm::themes::has_schnoebelen(const Solution& s)`.

- [ ] **Step 1: Write the failing test**

Three cases, fixtures built by the Global Constraints procedure. Open each
with these shape assertions:

- **positive** — a pawn promotes on S; a later ply captures on S; no ply in
  between departs S. `REQUIRE` a ply has `promotion` with `to == sq("<S>")`,
  and a later ply has `captured` with `to == sq("<S>")`, and no ply between
  them has `from == sq("<S>")`.
- **negative, it moved away and was captured elsewhere** — `REQUIRE` a ply
  after the promotion has `from == sq("<S>")`.
- **negative, it moved away and back before being captured on S** — this is
  the case the "never moved" clause exists for, and the one a naive
  implementation passes wrongly. `REQUIRE` that after the promotion there is a
  ply with `from == sq("<S>")` AND a still later ply with `captured` and
  `to == sq("<S>")`. The detector must answer false.

- [ ] **Step 2: Run it and watch it fail.**

- [ ] **Step 3: Implement**

```cpp
// A pawn promotes on square S; a later ply captures on S; and no ply in
// between moves a unit FROM S. The promoted unit is captured without ever
// having moved.
bool has_schnoebelen(const Solution& s) {
    for (size_t i = 0; i < s.plies.size(); ++i) {
        if (!s.plies[i].promotion) continue;
        const int sq = (int)s.plies[i].to;
        for (size_t j = i + 1; j < s.plies.size(); ++j) {
            if ((int)s.plies[j].from == sq) break;  // it moved: not Schnoebelen
            if (s.plies[j].captured && (int)s.plies[j].to == sq) return true;
        }
    }
    return false;
}
```

Register with `Needs::Solutions`, doc `"Schnoebelen: a promoted unit is captured on its promotion square without ever having moved."`, registry size 22.

- [ ] **Step 4: Run the tests.**
- [ ] **Step 5: Mutation-check** — delete the `break` line (the move-away-and-back negative must then fail); change `s.plies[j].from` to `s.plies[j].to` (must fail). Restore.
- [ ] **Step 6: Gate and commit**, message `feat(themes): schnoebelen -- a promoted unit captured before it ever moves`.

---

### Task 9: `pendulum`

**Files:**
- Modify: `src/core/themes/line_themes.h`, `src/core/themes/line_themes.cpp`, `src/core/themes/registry.cpp`
- Test: `src/core/tests/test_line_themes.cpp`

**Interfaces:**
- Consumes: `themes::trajectories(const Solution&)` from `trajectory.h`, already used by `has_switchback`. Read `has_switchback`'s implementation first to reuse its idiom for walking a trajectory's `squares`.
- Produces: `bool hm::themes::has_pendulum(const Solution& s)`.

- [ ] **Step 1: Write the failing test**

```cpp
TEST_CASE("pendulum: a unit oscillating between two squares", "[themes][line]") {
    // A trajectory a1-b1-a1-b1: two distinct squares, four entries.
    Solution s = play(FEN, MOVES);
    // Shape first: one trajectory of exactly two distinct squares, length >= 4.
    bool found = false;
    for (const auto& t : trajectories(s)) {
        std::set<uint8_t> d(t.squares.begin(), t.squares.end());
        if (t.squares.size() >= 4 && d.size() == 2) found = true;
    }
    REQUIRE(found);
    CHECK(has_pendulum(s));
}

TEST_CASE("pendulum: a single out-and-back is a switchback, not a pendulum",
          "[themes][line]") {
    Solution s = play(FEN, MOVES);   // a single out-and-back: 3 squares, 2 distinct
    for (const auto& t : trajectories(s)) REQUIRE(t.squares.size() <= 3);
    CHECK(has_pendulum(s) == false);
    CHECK(has_switchback(s));  // the overlap rule, stated in the spec
}

TEST_CASE("pendulum and switchback are NOT exclusive", "[themes][line]") {
    // Spec decision: a pendulum trajectory contains a switchback, and both are
    // reported -- exactly as ideal implies model implies pure. The v0.8
    // closed-walk bug came from leaving an overlap rule unstated.
    Solution s = play(FEN, MOVES);   // the four-move oscillation again
    CHECK(has_pendulum(s));
    CHECK(has_switchback(s));
}

TEST_CASE("pendulum: three distinct squares is a walk, not a pendulum",
          "[themes][line]") {
    Solution s = play(FEN, MOVES);   // three distinct squares, e.g. a1-b1-c1-b1
    bool three = false;
    for (const auto& t : trajectories(s)) {
        std::set<uint8_t> d(t.squares.begin(), t.squares.end());
        if (d.size() >= 3) three = true;
    }
    REQUIRE(three);
    CHECK_FALSE(has_pendulum(s));
}
```

`FEN` and `MOVES` stand for the fixture you construct and verify by the
Global Constraints procedure; the `REQUIRE`s above are what stop a drifted
fixture passing vacuously.

- [ ] **Step 2: Run it and watch it fail.**

- [ ] **Step 3: Implement**

```cpp
// One unit's trajectory visits exactly two distinct squares and has length
// >= 4 -- A,B,A,B, at least two returns. Deliberately NOT exclusive with
// switchback: a pendulum contains one, and both are reported.
bool has_pendulum(const Solution& s) {
    for (const auto& t : trajectories(s)) {
        if (t.squares.size() < 4) continue;
        std::set<uint8_t> distinct(t.squares.begin(), t.squares.end());
        if (distinct.size() == 2) return true;
    }
    return false;
}
```

Add `#include <set>` if `line_themes.cpp` lacks it. Register with
`Needs::Solutions`, doc `"Pendulum: a unit oscillates between exactly two squares, returning at least twice."`, registry size 23.

- [ ] **Step 4: Run the tests.**
- [ ] **Step 5: Mutation-check** — change `< 4` to `< 3` (the switchback negative must then fail); change `== 2` to `<= 2` (must fail, or add a case that kills it). Restore.
- [ ] **Step 6: Gate and commit**, message `feat(themes): pendulum -- a unit oscillating between two squares`.

---

### Task 10: Surfaces expose `needs`

Generic: no surface learns a theme name.

**Files:**
- Modify: `src/packages/cli/main.cpp` (`cmd_themes`)
- Modify: `src/packages/bindings/pymodule.cpp` (the `themes()` free function)
- Modify: `src/packages/web/helpmate_web/static/js/lib/themes.js` and the search panel that renders the multi-select
- Test: `src/packages/cli/CMakeLists.txt`, `src/packages/api/tests/`, `src/packages/web/tests/`

**Interfaces:**
- Consumes: `ThemeDef::needs`.
- Produces: `helpmate.themes()` dicts gain `"needs"`; `/v1/themes` entries gain `"needs"`.

- [ ] **Step 1: Write the failing tests**

CLI, in `src/packages/cli/CMakeLists.txt`:

```cmake
add_test(NAME cli_themes_shows_needs COMMAND helpmate themes)
set_tests_properties(cli_themes_shows_needs PROPERTIES
    PASS_REGULAR_EXPRESSION "needs: position")
```

Bindings, in `src/packages/bindings/tests/test_smoke.py`:

```python
def test_theme_registry_exposes_needs():
    entries = helpmate.themes()
    assert all("needs" in e for e in entries)
    by_name = {e["name"]: e for e in entries}
    assert by_name["homebase"]["needs"] == "position"
    assert by_name["set-play"]["needs"] == "plane"
    assert by_name["model"]["needs"] == "solutions"
```

API, in the existing themes test file under `src/packages/api/tests/`:

```python
def test_themes_endpoint_reports_needs(client):
    body = client.get("/v1/themes").json()
    assert all("needs" in t for t in body["themes"])
```

- [ ] **Step 2: Run them and watch them fail**

```bash
taskset -c 0-3 make test-bindings 2>&1 | tail -5
```
Expected: KeyError on `"needs"`.

- [ ] **Step 3: Implement**

In `pymodule.cpp`, where the registry is turned into dicts, add the field:

```cpp
    const char* n = t.needs == themes::Needs::Position ? "position"
                    : t.needs == themes::Needs::Plane ? "plane"
                                                      : "solutions";
    d["needs"] = n;
```

In `cmd_themes`, after the name line:

```cpp
        const char* n = t.needs == themes::Needs::Position ? "position"
                        : t.needs == themes::Needs::Plane ? "plane"
                                                          : "solutions";
        std::cout << "    needs: " << n << "\n";
```

The API needs no change — `/v1/themes` returns `helpmate.themes()` verbatim,
so the field flows through. Confirm that rather than assume it.

In the dashboard, mark entries whose `needs` is not `"solutions"` in the theme
multi-select, with a title attribute explaining that they also answer on
positions with saturated solution counts. Keep it data-driven — no theme names
in the JS.

- [ ] **Step 4: Run the tests**

```bash
taskset -c 0-3 make test-bindings 2>&1 | tail -2
taskset -c 0-3 make test-api 2>&1 | tail -2
taskset -c 0-3 make test-web 2>&1 | tail -2
taskset -c 0-3 make jstest 2>&1 | grep -E "^. (pass|fail)"
taskset -c 0-3 ctest --test-dir build -R cli_themes 2>&1 | tail -3
```
Expected: all PASS.

- [ ] **Step 5: Gate and commit**

```bash
taskset -c 0-3 make format-check && taskset -c 0-3 make lint && taskset -c 0-3 make typecheck
git add -A && git clang-format -q && git add -A
git commit -m "feat: CLI, API, bindings and dashboard report each theme's \`needs\`

Generic, not per-theme: every surface enumerates the registry, so a user can
see which themes answer without enumerating -- and therefore which answer on
saturated positions. /v1/themes needed no change at all, since it returns
helpmate.themes() verbatim.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 11: Documentation and version

**Files:**
- Modify: `README.md`, `docs/USAGE.md`, `CHANGELOG.md`, `VERSION`, `pyproject.toml`, `src/packages/api/pyproject.toml` (version and the `helpmate>=` floor), `src/packages/web/pyproject.toml`, `src/packages/api/helpmate_server/__init__.py`, `src/packages/web/helpmate_web/__init__.py`
- Modify: `docs/THEME-SELECTION.md` (mark the seven as shipped)

- [ ] **Step 1: Bump every declared version to 0.9.0**

Seven themes and a detector-signature change is a feature release, not a patch.

```bash
sed -i 's/0\.8\.2/0.9.0/' VERSION pyproject.toml src/packages/api/pyproject.toml \
  src/packages/web/pyproject.toml src/packages/api/helpmate_server/__init__.py \
  src/packages/web/helpmate_web/__init__.py
grep -rn "0\.8\.2" --include=pyproject.toml --include=*.py --include=VERSION . | grep -v build/ | grep -v CHANGELOG
```
Expected: no output. Also update the `"helpmate>=0.8.2,<0.9"` floor in
`src/packages/api/pyproject.toml` to `"helpmate>=0.9.0,<0.10"` — note the
upper bound changes too, which `sed` will not have done.

- [ ] **Step 2: Rebuild and reinstall so the version tests see it**

```bash
taskset -c 0-3 cmake -S . -B build >/dev/null && taskset -c 0-3 cmake --build build -j4 2>&1 | grep -E " error"
taskset -c 0-3 make install-dev GIT_CONFIG_GLOBAL=/dev/null 2>&1 | tail -1
taskset -c 0-3 make test-repo 2>&1 | tail -2
```
Expected: 14 passed. `GIT_CONFIG_GLOBAL=/dev/null` is required — this box's
gitconfig rewrites GitHub HTTPS to SSH and the build's dependency fetch
otherwise pops an invisible passphrase dialog.

- [ ] **Step 3: Write the CHANGELOG entry**

Add a `## [0.9.0] - <today>` section above `## [0.8.2]`, with an `### Added`
list of the seven themes and their definitions, and a `### Changed` note
covering the detector signature and the `needs` behaviour — specifically that
`mine` no longer enumerates for position- and plane-only themes and therefore
answers on saturated positions, which is a capability change users must know
about.

- [ ] **Step 4: Update `docs/USAGE.md` and `README.md`**

In the Themes section of `docs/USAGE.md`, add the seven definitions verbatim
from `helpmate themes` (run it and paste — do not retype), and add a short
subsection explaining `needs`: what the three values mean and that
position/plane themes answer on saturated positions. Update the theme count
in `README.md`'s Themes section. **Every example must be real output** — the
v0.8 README shipped two hallucinated sentences wrapped around real output.

- [ ] **Step 5: Mark the seven as shipped in the selection document**

In `docs/THEME-SELECTION.md`, move the seven rows into the `DONE` group so the
document does not drift from the build.

- [ ] **Step 6: Full gate**

```bash
taskset -c 0-3 make format-check; echo "format $?"
taskset -c 0-3 ./build/helpmate_tests "~[slow]" 2>&1 | tail -2
taskset -c 0-3 ctest --test-dir build 2>&1 | grep "tests passed"
for t in lint typecheck test-api test-bindings test-web test-repo; do
  printf '%-14s ' "$t"; taskset -c 0-3 make $t 2>&1 | tail -1
done
taskset -c 0-3 make jstest 2>&1 | grep -E "^. (pass|fail)"
```
Expected: everything green. `ctest` must be run **without** `-j` — there is a
documented shared-temp-dir race in `test_probe.cpp` under parallel ctest, and
CI runs it sequentially for that reason.

- [ ] **Step 7: Commit and open the PR**

```bash
git add -A && git commit -m "docs: theme round 2, release 0.9.0

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
timeout 180 env GIT_CONFIG_GLOBAL=/dev/null git -c credential.helper='!gh auth git-credential' \
  push https://github.com/osick/8pieces-helpmate.git HEAD:feat/themes-round-2
```
`origin` is an SSH URL, so network git operations need the explicit HTTPS URL
and `gh` as the credential helper, or they hang on a passphrase prompt. Then
open a PR against `main` and let CI run; `main` is branch-protected with six
required checks.
