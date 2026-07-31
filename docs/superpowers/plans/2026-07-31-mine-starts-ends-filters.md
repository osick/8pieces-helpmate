# `mine` starts/ends filters (v0.6.2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** let `mine` select positions by the shape of their solution set — how many distinct moves the optimal solutions begin with (`--starts`) and end with (`--ends`) — across CLI, HTTP API and Python; spec: `docs/superpowers/specs/2026-07-31-mine-starts-ends-filters-design.md`.

**Architecture:** A `MineFilter` struct replaces `mine`'s `(dtm, count)` parameters. A new `Tablebase::solution_shape(fen)` enumerates a position's optimal lines and reports the number of distinct first and last moves, plus whether the enumeration was exhaustive (it is not when the stored count is saturated at 255). `mine` evaluates the shape only for candidates that already passed the cheap dtm/count filters, and only when a shape filter is set.

**Tech Stack:** C++20 (GCC 13), Catch2, CMake; FastAPI + pytest for the server layer; pybind11 for the Python binding.

## Global Constraints

- **Match rule is exact**, like `--dtm`/`--count`: `--starts N` matches iff the number of distinct first moves equals N; `--ends N` likewise for last moves. Moves compare as SAN strings.
- **Validation:** `starts`/`ends` must be `>= 1`; when `count >= 0` is also given, each must be `<= count`. Violations are usage errors (CLI exit 3, HTTP 400) — never a silently empty result.
- **Saturated counts are skipped, not hidden:** a position whose stored count is `COUNT_SAT` (255, defined `src/chess/types.h:31`) cannot be enumerated exhaustively; when a shape filter is active such positions are skipped and counted. CLI prints the tally to stderr when non-zero; the API returns it as `skipped_saturated`.
- **`--max` is unchanged** — it caps returned rows.
- **Verified golden** (`KQvk`, position `8/7k/5K2/8/8/8/8/6Q1 b - - 0 1`, dtm 2, count 4): its four optimal lines are `Kh6 Qh2#`, `Kh6 Qh1#`, `Kh6 Qg6#`, `Kh8 Qg7#` — so **starts = 2**, **ends = 4**. Use these values verbatim; they were measured, not assumed.
- **Zero cost when unused:** shape evaluation runs only when a shape filter is set AND only for candidates that already matched dtm/count.
- Build: `PATH="$HOME/.local/bin:$PATH"`, `cmake --build build -j4`; never let CMake FetchContent clone from GitHub (SSH passphrase). FAST SUITE = `taskset -c 0-3 ./build/helpmate_tests "~[slow]"` — **never** the bare invocation (it adds a 30-60 minute `[slow]` lane). ctest: `cd build && taskset -c 0-3 ctest --output-on-failure`.
- Python changes require reinstalling the extension to test:
  `PATH="$HOME/.local/bin:$PATH" CXX=/usr/bin/g++-13 CC=/usr/bin/gcc-13 SKBUILD_CMAKE_ARGS="-DFETCHCONTENT_FULLY_DISCONNECTED=ON;-DFETCHCONTENT_SOURCE_DIR_CHESSMG=$PWD/build/_deps/chessmg-src;-DFETCHCONTENT_SOURCE_DIR_CATCH2=$PWD/build/_deps/catch2-src;-DFETCHCONTENT_SOURCE_DIR_JSON=$PWD/build/_deps/json-src" pip install -e ".[dev,server]"`
- **Never touch `~/tb`** — a multi-day 6-piece generation writes there. Use scratch directories.
- Commits are local (never push); message ends with the trailer line exactly: `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.

---

### Task 1: `MineFilter` struct and `mine` signature

**Files:**
- Modify: `src/probe/tablebase.h` (add struct above `class Tablebase`, change `mine`'s declaration ~line 39), `src/probe/tablebase.cpp` (`Tablebase::mine`, lines 112-125), `src/cli/main.cpp` (`cmd_mine`, ~line 173-187), `src/bindings/pymodule.cpp` (the `mine` lambda, ~lines 32-38)
- Test: `tests/cpp/test_probe.cpp` (append)

**Interfaces:**
- Produces:
  ```cpp
  struct MineFilter {
      int dtm    = -1;   // required, exact
      int count  = -1;   // optional, exact (-1 = any)
      int starts = -1;   // optional, exact (-1 = any)   [used from Task 3]
      int ends   = -1;   // optional, exact (-1 = any)   [used from Task 3]
  };
  void Tablebase::mine(const Material&, const MineFilter&,
                       const std::function<bool(const std::string&)>& cb) const;
  ```
- This task wires `starts`/`ends` through as inert fields; Task 3 makes them filter.

- [ ] **Step 1: Write the failing test**

Append to `tests/cpp/test_probe.cpp`. That file already has a shared fixture — `static std::string gen_dir()` (line 8) generates `KQvk` and `KPvk` once per test-binary run into a temp directory. Use it; do not create another.

```cpp
TEST_CASE("mine takes a MineFilter and behaves as before for dtm/count") {
    Tablebase tb(gen_dir());
    Material kqvk = *Material::parse("KQvk");

    std::vector<std::string> got;
    tb.mine(kqvk, MineFilter{.dtm = 2, .count = 4}, [&](const std::string& f) {
        got.push_back(f); return got.size() < 50;
    });
    REQUIRE_FALSE(got.empty());
    // every returned position really has dtm 2 and count 4
    for (const auto& f : got) {
        auto p = tb.probe(f);
        REQUIRE(p.has_value());
        CHECK(p->dtm == 2);
        CHECK(p->count == 4);
    }
    // the golden position is among them
    CHECK(std::find(got.begin(), got.end(),
                    "8/7k/5K2/8/8/8/8/6Q1 b - - 0 1") != got.end());

    // count unset (-1) must not filter
    size_t any_count = 0;
    tb.mine(kqvk, MineFilter{.dtm = 2}, [&](const std::string&) {
        ++any_count; return any_count < 50; });
    CHECK(any_count >= got.size());
}
```

- [ ] **Step 2: Run it**

`PATH="$HOME/.local/bin:$PATH" cmake --build build -j4` → FAILS: `'MineFilter' was not declared` / no matching call to `mine`.

- [ ] **Step 3: Implement**

`src/probe/tablebase.h` — add above `class Tablebase` (after the `MissingTableError` declaration):

```cpp
// Selection criteria for Tablebase::mine. -1 means "don't filter on this".
// Grouped in a struct so later filters (the web dashboard will want more) can
// be added without changing every call site again.
struct MineFilter {
    int dtm    = -1;   // required, exact
    int count  = -1;   // optional, exact
    int starts = -1;   // optional, exact: distinct first moves across optimal lines
    int ends   = -1;   // optional, exact: distinct final (mating) moves
};
```

Change the declaration (replacing the current `mine` line):

```cpp
    // stream FENs of canonical cells of material `m` matching `f`; stop as soon as
    // `cb` returns false.
    void mine(const Material& m, const MineFilter& f,
              const std::function<bool(const std::string&)>& cb) const;
```

`src/probe/tablebase.cpp` — replace the signature and the two filter lines; the body is otherwise unchanged:

```cpp
void Tablebase::mine(const Material& m, const MineFilter& f,
                      const std::function<bool(const std::string&)>& cb) const {
    const Slice* s = load(m);
    if (!s) throw MissingTableError("no table for " + m.name());
    Color stm = (f.dtm % 2) ? Color::White : Color::Black;  // parity invariant: wtm dtm odd, btm dtm even
    std::vector<PlacedPiece> pp;
    for (uint64_t c = 0; c < s->index.size(); ++c) {
        ValuePair v = s->reader.get(stm, c);
        if (v.dtm != (uint8_t)f.dtm) continue;
        if (f.count >= 0 && v.count != (uint8_t)f.count) continue;
        if (!s->index.decode(c, pp)) continue;
        if (!cb(Board::from_pieces(pp, stm).fen())) return;
    }
}
```

`src/cli/main.cpp` — in `cmd_mine`, replace the `tb.mine(*m, dtm, count, ...)` call with:

```cpp
    tb.mine(*m, MineFilter{.dtm = dtm, .count = count}, [&](const std::string& fen) {
```

`src/bindings/pymodule.cpp` — in the `mine` lambda body, replace the `t.mine(mat_or_throw(mat), dtm, count, ...)` call with:

```cpp
            t.mine(mat_or_throw(mat), MineFilter{.dtm = dtm, .count = count},
                   [&](const std::string& f) {
                       out.push_back(f); return (int)out.size() < max; });
```

(Keep the binding's `py::arg` list exactly as it is — Task 4 extends it.)

- [ ] **Step 4: Run it**

```
PATH="$HOME/.local/bin:$PATH" cmake --build build -j4
taskset -c 0-3 ./build/helpmate_tests "mine takes a MineFilter*"
taskset -c 0-3 ./build/helpmate_tests "~[slow]"
cd build && taskset -c 0-3 ctest --output-on-failure && cd ..
```
Expected: all pass. ctest matters here — `cli_mine` exercises the changed call site.

- [ ] **Step 5: Commit**

```bash
git add src/probe/tablebase.h src/probe/tablebase.cpp src/cli/main.cpp src/bindings/pymodule.cpp tests/cpp/test_probe.cpp
git commit   # refactor: mine takes a MineFilter struct
```

---

### Task 2: `solution_shape`

**Files:**
- Modify: `src/probe/tablebase.h` (declaration + a small result struct), `src/probe/tablebase.cpp` (implementation, next to `lines`)
- Test: `tests/cpp/test_probe.cpp` (append)

**Interfaces:**
- Consumes: `Tablebase::lines(fen, max)`, `Tablebase::probe(fen)`, `COUNT_SAT` (`src/chess/types.h:31`).
- Produces:
  ```cpp
  struct SolutionShape { int starts; int ends; bool exhaustive; };
  SolutionShape Tablebase::solution_shape(const std::string& fen) const;
  ```
  For an unsolvable position: `{0, 0, true}`. For a position whose stored count is `COUNT_SAT`: `{0, 0, false}` — the caller must not use the numbers.

- [ ] **Step 1: Write the failing test**

```cpp
TEST_CASE("solution_shape counts distinct first and last moves") {
    Tablebase tb(gen_dir());

    // Golden KQvk position: 4 optimal lines -- Kh6 Qh2#, Kh6 Qh1#, Kh6 Qg6#, Kh8 Qg7#
    // => 2 distinct first moves (Kh6, Kh8), 4 distinct mating moves.
    auto sh = tb.solution_shape("8/7k/5K2/8/8/8/8/6Q1 b - - 0 1");
    CHECK(sh.exhaustive);
    CHECK(sh.starts == 2);
    CHECK(sh.ends == 4);

    // A position already mated (dtm 0) has no moves at all.
    auto mated = tb.solution_shape("8/8/8/8/8/8/8/kQK5 b - - 0 1");
    CHECK(mated.exhaustive);
    CHECK(mated.starts == 0);
    CHECK(mated.ends == 0);

    // Unsolvable position: bare kings.
    auto uns = tb.solution_shape("8/8/8/8/8/4k3/8/4K3 w - - 0 1");
    CHECK(uns.exhaustive);
    CHECK(uns.starts == 0);
    CHECK(uns.ends == 0);
}
```

**Note to implementer:** confirm the dtm-0 FEN above really is mate-with-Black-to-move in the generated KQvk table (`./build/helpmate probe "8/8/8/8/8/8/8/kQK5 b - - 0 1" --tables <dir>` should print `dtm=0`); it is the same position the existing `cli_line_already_mate` ctest uses. If `lines()` returns one empty line for it (that is what that ctest documents), then `starts`/`ends` must both be 0 — make the implementation skip empty lines rather than indexing `line[0]` on an empty vector.

- [ ] **Step 2: Run it**

`PATH="$HOME/.local/bin:$PATH" cmake --build build -j4` → FAILS: `'solution_shape' is not a member of 'hm::Tablebase'`.

- [ ] **Step 3: Implement**

`src/probe/tablebase.h` — add next to `MineFilter`:

```cpp
// Shape of a position's optimal-solution set: how many distinct moves the
// solutions start with, and how many distinct moves they mate with.
// `exhaustive` is false when the stored optimal-line count is saturated
// (COUNT_SAT), in which case the solutions cannot be enumerated in full and
// starts/ends carry no meaning.
struct SolutionShape { int starts = 0; int ends = 0; bool exhaustive = true; };
```

and, in the public section next to `lines`:

```cpp
    // Distinct first/last moves across all optimal lines from `fen`.
    SolutionShape solution_shape(const std::string& fen) const;
```

`src/probe/tablebase.cpp` — implement after `lines`:

```cpp
SolutionShape Tablebase::solution_shape(const std::string& fen) const {
    auto p = probe(fen);
    if (!p) return {0, 0, true};                       // unsolvable: no solutions at all
    if (p->count >= (int)COUNT_SAT) return {0, 0, false};  // cannot enumerate exhaustively
    std::set<std::string> firsts, lasts;
    for (const auto& l : lines(fen, p->count)) {
        if (l.empty()) continue;                       // dtm 0: already mate, no moves
        firsts.insert(l.front());
        lasts.insert(l.back());
    }
    return {(int)firsts.size(), (int)lasts.size(), true};
}
```

Add `#include <set>` to the file's includes if absent.

- [ ] **Step 4: Run it**

```
PATH="$HOME/.local/bin:$PATH" cmake --build build -j4
taskset -c 0-3 ./build/helpmate_tests "solution_shape*"
taskset -c 0-3 ./build/helpmate_tests "~[slow]"
```
Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add src/probe/tablebase.h src/probe/tablebase.cpp tests/cpp/test_probe.cpp
git commit   # feat: solution_shape - distinct first/last moves of the optimal lines
```

---

### Task 3: Apply the shape filter inside `mine`

**Files:**
- Modify: `src/probe/tablebase.h` (`mine` gains a skipped-counter out-parameter — see Interfaces), `src/probe/tablebase.cpp` (`Tablebase::mine`)
- Test: `tests/cpp/test_probe.cpp` (append)

**Interfaces:**
- Consumes: `MineFilter` (Task 1), `solution_shape` (Task 2).
- Produces: `mine` filters on `starts`/`ends` when set, and reports how many candidates it skipped because their count was saturated:
  ```cpp
  void mine(const Material& m, const MineFilter& f,
            const std::function<bool(const std::string&)>& cb,
            uint64_t* skipped_saturated = nullptr) const;
  ```
  The pointer is optional so existing callers are unaffected; it is only ever written when a shape filter is active.

- [ ] **Step 1: Write the failing test**

```cpp
TEST_CASE("mine filters on distinct starting and mating moves") {
    Tablebase tb(gen_dir());
    Material kqvk = *Material::parse("KQvk");
    const std::string golden = "8/7k/5K2/8/8/8/8/6Q1 b - - 0 1";

    auto collect = [&](MineFilter f, int cap = 200) {
        std::vector<std::string> out;
        uint64_t skipped = 0;
        tb.mine(kqvk, f, [&](const std::string& s) {
            out.push_back(s); return (int)out.size() < cap; }, &skipped);
        return out;
    };

    // The golden position has starts 2, ends 4 -- it must appear only for those values.
    auto hit = collect(MineFilter{.dtm = 2, .count = 4, .starts = 2, .ends = 4});
    CHECK(std::find(hit.begin(), hit.end(), golden) != hit.end());

    auto miss_starts = collect(MineFilter{.dtm = 2, .count = 4, .starts = 3, .ends = 4});
    CHECK(std::find(miss_starts.begin(), miss_starts.end(), golden) == miss_starts.end());

    auto miss_ends = collect(MineFilter{.dtm = 2, .count = 4, .starts = 2, .ends = 3});
    CHECK(std::find(miss_ends.begin(), miss_ends.end(), golden) == miss_ends.end());

    // Every position returned under a starts/ends filter really has that shape.
    for (const auto& f : collect(MineFilter{.dtm = 4, .starts = 1, .ends = 1}, 40)) {
        auto sh = tb.solution_shape(f);
        CHECK(sh.exhaustive);
        CHECK(sh.starts == 1);
        CHECK(sh.ends == 1);
    }

    // Filtering on only one of the two works.
    for (const auto& f : collect(MineFilter{.dtm = 2, .starts = 1}, 40))
        CHECK(tb.solution_shape(f).starts == 1);
}
```

- [ ] **Step 2: Run it**

`PATH="$HOME/.local/bin:$PATH" cmake --build build -j4` → compiles (the extra argument has a default) but the test FAILS: positions are returned regardless of `starts`/`ends`, so `miss_starts`/`miss_ends` still contain the golden position.

- [ ] **Step 3: Implement**

In `src/probe/tablebase.cpp`, extend the loop body — the shape is evaluated only when a shape filter is set and only after the cheap filters pass:

```cpp
void Tablebase::mine(const Material& m, const MineFilter& f,
                      const std::function<bool(const std::string&)>& cb,
                      uint64_t* skipped_saturated) const {
    const Slice* s = load(m);
    if (!s) throw MissingTableError("no table for " + m.name());
    Color stm = (f.dtm % 2) ? Color::White : Color::Black;  // parity invariant: wtm dtm odd, btm dtm even
    const bool want_shape = f.starts >= 0 || f.ends >= 0;
    std::vector<PlacedPiece> pp;
    for (uint64_t c = 0; c < s->index.size(); ++c) {
        ValuePair v = s->reader.get(stm, c);
        if (v.dtm != (uint8_t)f.dtm) continue;
        if (f.count >= 0 && v.count != (uint8_t)f.count) continue;
        if (!s->index.decode(c, pp)) continue;
        std::string fen = Board::from_pieces(pp, stm).fen();
        if (want_shape) {
            SolutionShape sh = solution_shape(fen);
            if (!sh.exhaustive) {                       // count saturated: unknowable
                if (skipped_saturated) ++*skipped_saturated;
                continue;
            }
            if (f.starts >= 0 && sh.starts != f.starts) continue;
            if (f.ends   >= 0 && sh.ends   != f.ends)   continue;
        }
        if (!cb(fen)) return;
    }
}
```

Update the declaration in `src/probe/tablebase.h` to match (adding `uint64_t* skipped_saturated = nullptr`).

- [ ] **Step 4: Run it**

```
PATH="$HOME/.local/bin:$PATH" cmake --build build -j4
taskset -c 0-3 ./build/helpmate_tests "mine filters on distinct*"
taskset -c 0-3 ./build/helpmate_tests "~[slow]"
cd build && taskset -c 0-3 ctest --output-on-failure && cd ..
```
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/probe/tablebase.h src/probe/tablebase.cpp tests/cpp/test_probe.cpp
git commit   # feat: mine filters on distinct starting and mating moves
```

---

### Task 4: CLI flags `--starts` / `--ends`

**Files:**
- Modify: `src/cli/main.cpp` (usage text ~lines 29/50/71-81, `cmd_mine` ~line 173, flag parsing ~lines 274-318), `CMakeLists.txt` (new ctest cases near the existing `cli_mine`)
- Test: the ctest cases below

**Interfaces:**
- Consumes: `MineFilter` with `starts`/`ends` (Tasks 1+3).
- Produces: `helpmate mine <MATERIAL> --dtm D [--count C] [--starts N] [--ends N] [--max N]`.

- [ ] **Step 1: Write the failing ctest cases**

In `CMakeLists.txt`, next to the existing `cli_mine` test (the `CLI_TT` directory already holds a generated `KQvk`):

```cmake
# v0.6.2: shape filters. The golden KQvk position (dtm 2, count 4) has exactly
# 2 distinct first moves (Kh6, Kh8) and 4 distinct mating moves.
add_test(NAME cli_mine_shape COMMAND helpmate mine KQvk --dtm 2 --count 4 --starts 2 --ends 4 --max 200 --tables ${CLI_TT})
add_test(NAME cli_mine_shape_miss COMMAND helpmate mine KQvk --dtm 2 --count 4 --starts 3 --ends 4 --max 200 --tables ${CLI_TT})
add_test(NAME cli_mine_shape_badrange COMMAND helpmate mine KQvk --dtm 2 --count 2 --starts 5 --tables ${CLI_TT})
add_test(NAME cli_mine_shape_zero COMMAND helpmate mine KQvk --dtm 2 --starts 0 --tables ${CLI_TT})
set_tests_properties(cli_mine_shape PROPERTIES PASS_REGULAR_EXPRESSION "8/7k/5K2/8/8/8/8/6Q1 b - - 0 1" DEPENDS cli_gen)
set_tests_properties(cli_mine_shape_miss PROPERTIES FAIL_REGULAR_EXPRESSION "8/7k/5K2/8/8/8/8/6Q1 b" DEPENDS cli_gen)
set_tests_properties(cli_mine_shape_badrange PROPERTIES PASS_REGULAR_EXPRESSION "error.*--starts" DEPENDS cli_gen)
set_tests_properties(cli_mine_shape_zero PROPERTIES PASS_REGULAR_EXPRESSION "error.*--starts" DEPENDS cli_gen)
```

- [ ] **Step 2: Run them**

`PATH="$HOME/.local/bin:$PATH" cmake --build build -j4 && cd build && taskset -c 0-3 ctest -R cli_mine_shape --output-on-failure; cd ..`
Expected: FAIL — the flags are unknown, so `--starts` lands in the positional list and the material parse fails (exit 3).

- [ ] **Step 3: Implement**

In `src/cli/main.cpp`:

1. Declare the two new variables alongside the existing ones (~line 274):
```cpp
    int threads = 1, dtm = -1, count = -1, maxn = 10, starts = -1, ends = -1;
```
2. Add them to the "flag takes a value" predicate (~line 282):
```cpp
        return a == "--tables" || a == "--threads" || a == "--dtm" || a == "--count" ||
               a == "--max" || a == "--starts" || a == "--ends";
```
3. Parse them next to the others (~line 305):
```cpp
        else if (a == "--starts")  set_int(a, i, starts);
        else if (a == "--ends")    set_int(a, i, ends);
```
4. Pass them to `cmd_mine` (~line 318): `return cmd_mine(pos, tables, dtm, count, maxn, starts, ends);`
5. Extend `cmd_mine`:
```cpp
int cmd_mine(const std::vector<std::string>& pos, const std::string& tables, int dtm, int count,
             int maxn, int starts, int ends) {
    if (pos.empty()) { std::cerr << "error: mine needs a MATERIAL argument (e.g. KQvk)\n\n"; usage(); return 3; }
    if (dtm < 0) { std::cerr << "error: mine requires --dtm D\n\n"; usage(); return 3; }
    for (auto [flag, val] : {std::pair{"--starts", starts}, std::pair{"--ends", ends}}) {
        if (val == -1) continue;                       // not given
        if (val < 1) {
            std::cerr << "error: " << flag << " must be at least 1\n"; return 3;
        }
        if (count >= 0 && val > count) {
            std::cerr << "error: " << flag << " " << val << " cannot exceed --count " << count
                      << " (a position with " << count << " solution(s) has at most "
                      << count << " distinct starting/mating moves)\n";
            return 3;
        }
    }
    auto m = Material::parse(pos[0]);
    if (!m) { std::cerr << "error: not a valid material string: \"" << pos[0] << "\"\n"; return 3; }
    Tablebase tb(tables);
    int printed = 0;
    uint64_t skipped = 0;
    tb.mine(*m, MineFilter{.dtm = dtm, .count = count, .starts = starts, .ends = ends},
            [&](const std::string& fen) {
                if (printed >= maxn) return false;  // handles --max 0 (print none), matches `line --all`'s pre-check
                std::cout << fen << "\n";
                ++printed;
                return printed < maxn;
            }, &skipped);
    if (skipped)
        std::cerr << "note: skipped " << skipped
                  << " position(s) whose solution count is saturated (255+): their"
                     " solutions cannot be enumerated exhaustively\n";
    return 0;
}
```
6. Usage text: add `[--starts N] [--ends N]` to the `mine` synopsis line, describe both flags in the options block next to `--count`, and add one example:
```
"  helpmate mine KQvk --dtm 2 --count 4 --starts 2 --ends 4 --tables tt\n"
```
Descriptions to use verbatim:
```
"  --starts N     mine: optional, exact number of distinct first moves across\n"
"                 the optimal solutions (must be >= 1, and <= --count if given)\n"
"  --ends N       mine: optional, exact number of distinct mating moves\n"
```

- [ ] **Step 4: Run them**

```
PATH="$HOME/.local/bin:$PATH" cmake --build build -j4
cd build && taskset -c 0-3 ctest --output-on-failure && cd ..
taskset -c 0-3 ./build/helpmate_tests "~[slow]"
```
Expected: all ctest cases pass (including the four new ones) and the fast suite stays green.

- [ ] **Step 5: Manual check, captured for the report**

```bash
D=$(mktemp -d); ./build/helpmate gen KQvk --tables $D >/dev/null
./build/helpmate mine KQvk --dtm 2 --count 4 --starts 2 --ends 4 --max 3 --tables $D
./build/helpmate mine KQvk --dtm 2 --count 4 --starts 1 --max 3 --tables $D
./build/helpmate mine KQvk --dtm 2 --count 2 --starts 5 --tables $D; echo "exit=$?"
rm -rf $D
```
Paste the real output into your report.

- [ ] **Step 6: Commit**

```bash
git add src/cli/main.cpp CMakeLists.txt
git commit   # feat(cli): mine --starts/--ends filters
```

---

### Task 5: Python binding and HTTP API

**Files:**
- Modify: `src/bindings/pymodule.cpp` (the `mine` lambda), `server/helpmate_server/app.py` (the `/v1/mine` route)
- Test: `tests/python/test_smoke.py` (append), `tests/server/test_api_mine.py` (append)

**Interfaces:**
- Consumes: `MineFilter`, `mine`'s `skipped_saturated` out-parameter (Tasks 1+3).
- Produces:
  - Python: `Tablebase.mine(material, dtm, count=-1, max=100, starts=-1, ends=-1) -> list[str]`
  - HTTP: `GET /v1/mine?material=&dtm=&count=&max=&starts=&ends=` → `{"fens": [...], "truncated": bool, "skipped_saturated": int}`; invalid `starts`/`ends` → 400 with the existing error envelope.

- [ ] **Step 1: Write the failing tests**

Append to `tests/python/test_smoke.py`:

```python
def test_mine_shape_filters(tables):
    tb = helpmate.Tablebase(tables)
    golden = "8/7k/5K2/8/8/8/8/6Q1 b - - 0 1"
    # golden has 2 distinct first moves (Kh6, Kh8) and 4 distinct mating moves
    hit = tb.mine("KQvk", dtm=2, count=4, starts=2, ends=4, max=200)
    assert golden in hit
    assert golden not in tb.mine("KQvk", dtm=2, count=4, starts=3, max=200)
    # omitting the new kwargs reproduces the old behaviour
    assert tb.mine("KQvk", dtm=2, count=4, max=5) == tb.mine("KQvk", dtm=2, count=4, max=5)
    for f in tb.mine("KQvk", dtm=4, starts=1, ends=1, max=20):
        ls = tb.lines(f)
        assert len({l[0] for l in ls}) == 1 and len({l[-1] for l in ls}) == 1
```

Append to `tests/server/test_api_mine.py`:

```python
GOLDEN = "8/7k/5K2/8/8/8/8/6Q1 b - - 0 1"

def test_mine_shape_filters(client):
    r = client.get("/v1/mine", params={"material": "KQvk", "dtm": 2, "count": 4,
                                       "starts": 2, "ends": 4, "max": 200})
    assert r.status_code == 200
    body = r.json()
    assert GOLDEN in body["fens"]
    assert body["skipped_saturated"] == 0

    r = client.get("/v1/mine", params={"material": "KQvk", "dtm": 2, "count": 4,
                                       "starts": 3, "max": 200})
    assert r.status_code == 200 and GOLDEN not in r.json()["fens"]

def test_mine_shape_validation(client):
    r = client.get("/v1/mine", params={"material": "KQvk", "dtm": 2, "count": 2, "starts": 5})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "invalid_filter"

    r = client.get("/v1/mine", params={"material": "KQvk", "dtm": 2, "ends": 0})
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_filter"
```

- [ ] **Step 2: Run them**

```
taskset -c 0-3 python -m pytest tests/server/test_api_mine.py -v
```
Expected: FAIL — `starts`/`ends` are ignored, so the golden position appears in the `starts=3` result and the validation cases return 200.

(The Python-binding test cannot run until Step 3's reinstall; that is expected.)

- [ ] **Step 3: Implement**

`src/bindings/pymodule.cpp` — replace the `mine` lambda and its `py::arg` list:

```cpp
        .def("mine", [](const Tablebase& t, const std::string& mat, int dtm, int count,
                        int max, int starts, int ends) {
            std::vector<std::string> out;
            t.mine(mat_or_throw(mat),
                   MineFilter{.dtm = dtm, .count = count, .starts = starts, .ends = ends},
                   [&](const std::string& f) {
                       out.push_back(f); return (int)out.size() < max; });
            return out;
        }, py::arg("material"), py::arg("dtm"), py::arg("count") = -1, py::arg("max") = 100,
           py::arg("starts") = -1, py::arg("ends") = -1)
```

`server/helpmate_server/app.py` — in the `/v1/mine` route, accept the two parameters, validate them, and pass them through. The route currently calls `_tb(chain, d).mine(material, dtm, count, clamped + 1)`; the binding takes `max` positionally in that slot, so keep that call shape and add the new keywords:

```python
    @app.get("/v1/mine")
    def mine(material: str, dtm: int, count: int = -1, max: int = 100,
             starts: int = -1, ends: int = -1):
        for name, val in (("starts", starts), ("ends", ends)):
            if val == -1:
                continue
            if val < 1:
                return JSONResponse(status_code=400, content=error_json(
                    "invalid_filter", f"{name} must be at least 1"))
            if count >= 0 and val > count:
                return JSONResponse(status_code=400, content=error_json(
                    "invalid_filter",
                    f"{name}={val} cannot exceed count={count}",
                    hint="a position with N solutions has at most N distinct "
                         "starting or mating moves"))
        d, resp = _resolve_or_response(material)
        if resp is not None:
            return resp
        clamped = min(max, mine_cap)
        fut = pool.submit(_tb(chain, d).mine, material, dtm, count, clamped + 1,
                          starts, ends)
        try:
            fens = fut.result(timeout=mine_timeout)
        except FutTimeout:
            return {"fens": [], "truncated": True, "note": "timeout",
                    "skipped_saturated": 0}
        return {"fens": fens[:clamped], "truncated": len(fens) > clamped,
                "skipped_saturated": 0}
```

**The `skipped_saturated` value must be real, not a hardcoded 0** — a field that always reads 0 becomes a lie the first time someone mines a saturated slice. Surface the tally through a second binding entry point, leaving `mine`'s existing signature and return type untouched so current Python callers keep working. In `src/bindings/pymodule.cpp`, alongside `mine`:

```cpp
        .def("_mine_with_stats", [](const Tablebase& t, const std::string& mat, int dtm,
                                    int count, int max, int starts, int ends) {
            std::vector<std::string> out;
            uint64_t skipped = 0;
            t.mine(mat_or_throw(mat),
                   MineFilter{.dtm = dtm, .count = count, .starts = starts, .ends = ends},
                   [&](const std::string& f) {
                       out.push_back(f); return (int)out.size() < max; },
                   &skipped);
            return std::make_pair(out, skipped);      // -> (list[str], int) in Python
        }, py::arg("material"), py::arg("dtm"), py::arg("count") = -1, py::arg("max") = 100,
           py::arg("starts") = -1, py::arg("ends") = -1)
```

Expose it on the wrapper class in `python/helpmate/__init__.py` (that file already subclasses the raw binding to add `stats`):

```python
    def mine_with_stats(self, material: str, dtm: int, count: int = -1, max: int = 100,
                        starts: int = -1, ends: int = -1) -> tuple[list, int]:
        """Like mine(), but also returns how many positions were skipped because
        their optimal-line count is saturated (255+) and therefore not enumerable."""
        return self._mine_with_stats(material, dtm, count, max, starts, ends)
```

and have the route use it:

```python
        fut = pool.submit(_tb(chain, d).mine_with_stats, material, dtm, count,
                          clamped + 1, starts, ends)
        try:
            fens, skipped = fut.result(timeout=mine_timeout)
        except FutTimeout:
            return {"fens": [], "truncated": True, "note": "timeout",
                    "skipped_saturated": 0}
        return {"fens": fens[:clamped], "truncated": len(fens) > clamped,
                "skipped_saturated": int(skipped)}
```

Add one assertion to `tests/python/test_smoke.py` proving the pair shape:

```python
def test_mine_with_stats_returns_pair(tables):
    tb = helpmate.Tablebase(tables)
    fens, skipped = tb.mine_with_stats("KQvk", dtm=2, count=4, starts=2, ends=4, max=5)
    assert isinstance(fens, list) and isinstance(skipped, int)
    assert skipped == 0          # KQvk has no saturated-count positions
```

- [ ] **Step 4: Rebuild, reinstall, run**

```
PATH="$HOME/.local/bin:$PATH" cmake --build build -j4
PATH="$HOME/.local/bin:$PATH" CXX=/usr/bin/g++-13 CC=/usr/bin/gcc-13 SKBUILD_CMAKE_ARGS="-DFETCHCONTENT_FULLY_DISCONNECTED=ON;-DFETCHCONTENT_SOURCE_DIR_CHESSMG=$PWD/build/_deps/chessmg-src;-DFETCHCONTENT_SOURCE_DIR_CATCH2=$PWD/build/_deps/catch2-src;-DFETCHCONTENT_SOURCE_DIR_JSON=$PWD/build/_deps/json-src" pip install -e ".[dev,server]"
taskset -c 0-3 python -m pytest tests/python tests/server -v
```
Expected: all pass, including the four new tests.

- [ ] **Step 5: Commit**

```bash
git add src/bindings/pymodule.cpp server/helpmate_server/app.py python/helpmate/__init__.py tests/python/test_smoke.py tests/server/test_api_mine.py
git commit   # feat: starts/ends filters in the Python binding and HTTP API
```

---

### Task 6: Format-version diagnostics

**Files:**
- Modify: `src/format/table_file.h` (a small enum + a second entry point), `src/format/table_file.cpp` (`TableReader::open` validation, lines ~125-148), `src/probe/tablebase.cpp` (`Tablebase::load`, lines ~25-47)
- Test: `tests/cpp/test_table_file.cpp` (append)

**Interfaces:**
- Consumes: the existing `TableReader::open`.
- Produces: `TableReader::open` keeps returning `std::optional<TableReader>`; a new
  ```cpp
  enum class OpenError { None, NotFound, Unreadable, UnsupportedVersion };
  static std::optional<TableReader> open(const std::string& path, OpenError* err);
  ```
  overload reports *why* a file could not be opened, and `Tablebase::load` uses it to throw a clear "upgrade helpmate" error instead of reporting a present-but-unreadable table as missing.

- [ ] **Step 1: Write the failing test**

```cpp
TEST_CASE("a future-format table reports UnsupportedVersion, not NotFound") {
    namespace fs = std::filesystem;
    fs::path dir = fs::temp_directory_path() / ("hm_future_" + std::to_string(::getpid()));
    fs::create_directories(dir);
    std::string path = (dir / "Kvk.hm").string();

    // Write a valid marker, then bump its version byte to a value this build
    // does not know -- exactly what an older binary sees when it meets a newer table.
    TableWriter::write_unsolvable(path, *Material::parse("Kvk"), 462, "{}");
    {
        std::fstream f(path, std::ios::in | std::ios::out | std::ios::binary);
        uint32_t v = 99;
        f.seekp(offsetof(TableHeader, version));
        f.write(reinterpret_cast<const char*>(&v), sizeof(v));
    }

    TableReader::OpenError err = TableReader::OpenError::None;
    auto r = TableReader::open(path, &err);
    CHECK_FALSE(r.has_value());
    CHECK(err == TableReader::OpenError::UnsupportedVersion);

    // A genuinely absent file is still NotFound.
    TableReader::OpenError err2 = TableReader::OpenError::None;
    CHECK_FALSE(TableReader::open((dir / "KQvk.hm").string(), &err2).has_value());
    CHECK(err2 == TableReader::OpenError::NotFound);

    fs::remove_all(dir);
}
```

- [ ] **Step 2: Run it**

`PATH="$HOME/.local/bin:$PATH" cmake --build build -j4` → FAILS: `'OpenError' is not a member of 'hm::TableReader'`.

- [ ] **Step 3: Implement**

In `src/format/table_file.h`, inside `class TableReader`'s public section:

```cpp
    // Why open() returned nullopt. UnsupportedVersion means the file IS a helpmate
    // table, but was written by a newer build than this one.
    enum class OpenError { None, NotFound, Unreadable, UnsupportedVersion };
    static std::optional<TableReader> open(const std::string& path, OpenError* err);
```
(keep the existing single-argument `open` declaration; implement it as a forwarding call.)

In `src/format/table_file.cpp`: set `*err` at each failure point — `NotFound` when the file cannot be opened/stat'ed, `UnsupportedVersion` when the magic is `HM8P` but the version/flag combination is not one this build accepts, `Unreadable` for every other malformed case (bad magic, bad payload size, json_len overrun). The single-argument overload becomes:

```cpp
std::optional<TableReader> TableReader::open(const std::string& path) {
    OpenError ignored = OpenError::None;
    return open(path, &ignored);
}
```

Keep the existing validation logic exactly as it is — only add the error reporting. Note the current check accepts `version == 1 || (version == 2 && marker)`; the "unsupported version" case is therefore `magic ok && (version > 2 || (version == 2 && !marker))`. Treat `version == 2 && !marker` as `Unreadable` (it is malformed, not futuristic) and `version > 2` as `UnsupportedVersion`.

In `src/probe/tablebase.cpp`'s `Tablebase::load`, replace `auto r = TableReader::open(path);` with the reporting overload and throw on the unsupported case, before the existing identity checks:

```cpp
    TableReader::OpenError oerr = TableReader::OpenError::None;
    auto r = TableReader::open(path, &oerr);
    if (!r && oerr == TableReader::OpenError::UnsupportedVersion)
        throw std::runtime_error("table " + path + " was written by a newer helpmate"
                                 " (unsupported table format version); upgrade this build");
```

- [ ] **Step 4: Run it**

```
PATH="$HOME/.local/bin:$PATH" cmake --build build -j4
taskset -c 0-3 ./build/helpmate_tests "a future-format table*"
taskset -c 0-3 ./build/helpmate_tests "~[slow]"
cd build && taskset -c 0-3 ctest --output-on-failure && cd ..
```
Expected: all pass. The existing malformed-header tests must stay green — they now exercise the `Unreadable` path.

- [ ] **Step 5: Commit**

```bash
git add src/format/table_file.h src/format/table_file.cpp src/probe/tablebase.cpp tests/cpp/test_table_file.cpp
git commit   # fix: distinguish a future-format table from a missing one
```

---

### Task 7: Docs, changelog, version bump

**Files:**
- Modify: `docs/USAGE.md` (the `mine` section and the API section), `README.md` (one line), `CHANGELOG.md`, `pyproject.toml`, `server/helpmate_server/__init__.py`, `tests/server/test_packaging.py`, `src/version.h`, `CMakeLists.txt:2`
- Test: the existing suites

**Interfaces:**
- Consumes: everything above.

- [ ] **Step 1: Version bump to 0.6.2**

Five places, all of which must agree: `pyproject.toml`'s `version`, `server/helpmate_server/__init__.py`'s `__version__`, the expected value in `tests/server/test_packaging.py`, `HELPMATE_VERSION` in `src/version.h:9`, and `project(helpmate VERSION ...)` in `CMakeLists.txt:2`. Check `CMakeLists.txt`'s `cli_version` ctest regex too — it pins the version string.

- [ ] **Step 2: Docs**

`docs/USAGE.md`:
- In the `mine` section: document `--starts N` and `--ends N`, the exact-match rule, the `<= --count` validation, and the saturated-count skip with its stderr note. Include a real captured example — run `helpmate mine KQvk --dtm 2 --count 4 --starts 2 --ends 4 --max 3` against a scratch directory and paste the actual output, plus a short explanation of why the golden position has starts 2 and ends 4 (its four lines are `Kh6 Qh2#`, `Kh6 Qh1#`, `Kh6 Qg6#`, `Kh8 Qg7#`).
- In the API section: add `starts` and `ends` to `/v1/mine`'s parameter list, show the `skipped_saturated` response field, and give a real `curl` example captured from a running server.
- Add one sentence somewhere sensible in the tables/format discussion noting that a table written by a newer helpmate now reports "upgrade this build" rather than appearing missing.

`README.md`: one line in the CLI overview mentioning the new filters.

`CHANGELOG.md`: a `## [0.6.2] - <date>` section above `[0.6.1]` covering the filters (CLI, API, Python), the `MineFilter` refactor, and the format-version diagnostics.

- [ ] **Step 3: Full verification**

```
PATH="$HOME/.local/bin:$PATH" cmake --build build -j4
taskset -c 0-3 ./build/helpmate_tests "~[slow]"
cd build && taskset -c 0-3 ctest --output-on-failure && cd ..
taskset -c 0-3 python -m pytest tests/python tests/server -v
./build/helpmate --version      # helpmate 0.6.2
```
All four must be green before committing.

- [ ] **Step 4: Commit**

```bash
git add docs/USAGE.md README.md CHANGELOG.md pyproject.toml server/helpmate_server/__init__.py tests/server/test_packaging.py src/version.h CMakeLists.txt
git commit   # release: v0.6.2 - mine shape filters, docs, version bump
```

---

## Verification checklist (whole plan)

- C++ fast suite, ctest, and both Python suites green; `helpmate --version` reports 0.6.2.
- The golden position is returned by `--starts 2 --ends 4` and excluded by any other combination, through all three surfaces (CLI, HTTP, Python).
- `mine` without shape filters returns exactly what it returned before (Task 1's regression test plus the untouched `cli_mine` ctest).
- Invalid filter combinations produce a usage error, never a silently empty result.
- A future-format table reports "upgrade this build", not "no table".
