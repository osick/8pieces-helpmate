# Building helpmate

Everything needed to build the C++ CLI/library, run the test suites, measure
coverage, and build the Python package — including the offline/pre-fetched
dependency workflow for machines whose git configuration rewrites GitHub HTTPS
URLs to SSH.

## Prerequisites

| Requirement | Version | Used for |
|---|---|---|
| GCC (`g++`) | ≥ 13 | C++20 compiler for the core, tests and CLI |
| CMake | ≥ 3.24 (`cmake_minimum_required` in `CMakeLists.txt`) | build system |
| GNU make | any recent | convenience targets (`make build`, `make test`, …) |
| git | any recent | first-configure `FetchContent` clone of the three dependencies |
| Python | ≥ 3.9 | optional: the `helpmate` Python package (`pip install .`) |
| gcovr + `gcov-13` | any recent gcovr | optional: `make coverage` |
| pytest, python-chess ≥ 1.10 | — | optional: the Python test suite (installed by `pip install -e .[dev]`) |

The build is developed and tested with GCC 13 on Linux. On distributions whose
default `g++`/`cc` predate GCC 13 (e.g. openSUSE Leap, where this project was
developed), point the build at a newer compiler explicitly:

```bash
CXX=/usr/bin/g++-13 CC=/usr/bin/gcc-13 make test
```

If your distribution's CMake is older than 3.24, a user-local CMake works fine
(e.g. `pip install cmake`, or a binary release on your `PATH` — the development
box uses one in `~/.local/bin`).

## Dependencies (FetchContent)

The first CMake configure fetches three pinned dependencies with
`FetchContent` into `build/_deps/`:

| Dependency | Pin | Role |
|---|---|---|
| [osick/ChessMG](https://github.com/osick/ChessMG) | commit `efbe11d9fe85ce186aadfbefa813818c03ae2c18` | move generation core |
| [Catch2](https://github.com/catchorg/Catch2) | `v3.5.4` | C++ test framework |
| [nlohmann/json](https://github.com/nlohmann/json) | `v3.11.3` | stats sidecar and Python-facing JSON |

After that first fetch, rebuilds are fully offline — the sources stay under
`build/_deps/` and nothing is re-cloned.

### Offline / pre-fetched builds (and the HTTPS→SSH gitconfig pitfall)

On machines whose `~/.gitconfig` rewrites `https://github.com/` to SSH (via
`url.….insteadOf`), any fresh `FetchContent` clone triggers an SSH passphrase
prompt — including the *separate* CMake configure that `pip install` runs (see
[Python package](#python-package-pip)). Two ways around it:

1. **Reuse already-fetched sources** (preferred; this is exactly what
   `make coverage` does). Point CMake at an existing `build/_deps` from any
   earlier configure:

   ```bash
   cmake -S . -B <builddir> \
     -DFETCHCONTENT_FULLY_DISCONNECTED=ON \
     -DFETCHCONTENT_SOURCE_DIR_CHESSMG=$PWD/build/_deps/chessmg-src \
     -DFETCHCONTENT_SOURCE_DIR_CATCH2=$PWD/build/_deps/catch2-src \
     -DFETCHCONTENT_SOURCE_DIR_JSON=$PWD/build/_deps/json-src
   ```

   With `FETCHCONTENT_FULLY_DISCONNECTED=ON` CMake never touches the network
   (or git) for these dependencies.

2. **One-off fetch with the rewrite disabled**: run the first configure with
   `GIT_CONFIG_GLOBAL=/dev/null` so the `insteadOf` rewrite doesn't apply, then
   build normally (rebuilds are offline anyway).

On CI runners and ordinary machines without such rewrites, plain HTTPS cloning
works out of the box and none of this is needed.

## Package layout

The C++ tree lives under `src/core/` (the engine: generator, indexing,
probe, storage) with the CLI and Python bindings as thin consumers in
`src/packages/cli/` and `src/packages/bindings/`. Above that, three
separately installable distributions, each with its own
`pyproject.toml`/`CMakeLists.txt` and its own test suite under
`src/packages/<name>/tests/`:

| Distribution | Path | Contains |
|---|---|---|
| `helpmate` | root `pyproject.toml` (builds `src/core` + `src/packages/cli` + `src/packages/bindings`) | the compiled `helpmate` CLI binary and the `helpmate` Python module |
| `helpmate-api` | `src/packages/api/` | the FastAPI service (`helpmate-server`) and `helpmate-tables` |
| `helpmate-web` | `src/packages/web/` | the static dashboard, served by `helpmate-server` when installed |

`helpmate-api` depends on `helpmate`, and nothing is published to PyPI yet,
so they must install in dependency order — `make install` does this for all
three:

```bash
make install
# equivalent to:
python -m pip install .
python -m pip install ./src/packages/api ./src/packages/web
```

## Makefile targets

The Makefile is a thin wrapper over CMake; every target can be prefixed with
`CXX=… CC=…` as shown above. Variables: `BUILD` (default `build`), `COVBUILD`
(default `build-cov`), `GCOV` (default `gcov-13`).

### `make configure`

Runs `cmake -S . -B build`. `CMAKE_BUILD_TYPE` defaults to `Release` (set in
`CMakeLists.txt` when unspecified).

### `make build`

Configures (if needed) and runs `cmake --build build -j`. Produces:

- `build/helpmate` — the CLI binary,
- `build/helpmate_tests` — the Catch2 test binary,
- static libraries `helpmate_core` and `chessmg_core`.

### `make test`

Builds, then runs the **fast suite** via
`ctest --test-dir build --output-on-failure`: the Catch2 cases *not* tagged
`[slow]` (the CMake test discovery uses the spec `~[slow]`) plus the CLI
integration tests (`cli_gen`, `cli_probe`, …). Note ctest is run without `-j`;
keep it sequential — a pre-existing shared-temp-dir race in `test_probe.cpp`
shows up only under parallel ctest.

### `make slowtest`

Runs `./build/helpmate_tests "[slow]"` — the exhaustive/multithreaded
determinism cases excluded from `make test` (full KPvkp closure generation,
N-thread vs 1-thread byte-identity; tens of minutes each).

### `make stress TABLES=<dir> [ITERS=n]`

Regression stress for the 5-piece generation crash investigation (bug #21):
repeatedly runs the oversubscribed `KNvkqr` root-slice generation via
`tests/stress_oversubscribed_gen.sh` (default `ITERS=5`). Requirements:

- `TABLES` must point at a directory already holding the cached sub-slice
  tables for `KNvkqr` (generate them once first);
- `taskset` must be available (which is why this cannot be a ctest case);
- use a **stock Release build** — instrumented/sanitizer builds mask the
  original fault (see the script header).

### `make coverage`

Line/function/branch coverage of `src/` with gcovr. It:

1. configures a *separate* tree `build-cov/` with `-DHELPMATE_COVERAGE=ON
   -DCMAKE_BUILD_TYPE=Debug` (adds `--coverage -O0 -g` to `helpmate_core`
   only; the normal `build/` tree is untouched),
2. reuses the dependency sources already under `build/_deps` via
   `FETCHCONTENT_FULLY_DISCONNECTED` + `FETCHCONTENT_SOURCE_DIR_*` — so **run
   `make build` or `make test` at least once first**; it never clones anything,
3. runs the fast suite in the coverage tree,
4. runs gcovr and prints the summary, writing an HTML report to
   `build-cov/coverage/index.html` and the text summary to
   `build-cov/coverage-summary.txt`.

Prerequisite: `pip install gcovr` into whatever Python environment provides
your dev tooling.

**`GCOV=gcov-13`**: gcovr must invoke the `gcov` binary matching the GCC
version that compiled the coverage build. The distro's default `gcov` is often
an older system-GCC version and hard-errors with "Version mismatch gcc/gcov"
against a GCC-13 build; the Makefile therefore defaults to `GCOV=gcov-13`.
Override with `make coverage GCOV=/path/to/gcov-N` if you compile with a
different GCC. The recipe also passes `--gcov-ignore-parse-errors=all`: GCC's
coverage counters are not thread-safe (upstream GCC bug 68080), and the
multithreaded generator tests can produce "suspicious hit" records that would
otherwise abort gcovr (see the Coverage section of the README for the honest
interpretation of the resulting numbers).

### `make clean`

Removes `build/` and `build-cov/`.

### `make install`

`python -m pip install .` then `python -m pip install ./src/packages/api
./src/packages/web` — all three distributions, in the order `helpmate-api`
requires.

### Per-package test targets

Each installable distribution owns its own test suite; these wrap the
commands the CI jobs run:

- `make test-core` — builds, then `$(BUILD)/helpmate_tests "~[slow]"` (the
  same Catch2 cases `make test`'s ctest run drives, invoked directly).
- `make test-cli` — builds, then `ctest --test-dir $(BUILD) -R "^cli_"` (just
  the CLI integration tests).
- `make test-api` — `pytest src/packages/api/tests` (requires `helpmate` and
  `helpmate-api` installed with the `dev` extra).
- `make test-web` — `make jstest` then `pytest src/packages/web/tests/ui`
  (requires `helpmate-web`'s `dev` extra, which includes Playwright).
- `make test-bindings` — `pytest src/packages/bindings/tests`.
- `make test-repo` — `pytest tests/repo`, the repo-level checks (e.g. that
  `VERSION` agrees with every `pyproject.toml` and `helpmate --version`).
- `make test-all` — `test` (the C++/CLI ctest suite) plus all five of the
  above.

## Plain CMake (without make)

```bash
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build -j
ctest --test-dir build --output-on-failure   # fast suite
./build/helpmate_tests "[slow]"              # slow suite, explicitly
```

Options: `-DHELPMATE_COVERAGE=ON` (coverage instrumentation on
`helpmate_core`), `-DHELPMATE_PYTHON=ON` (build the pybind11 module; normally
you never set this by hand — `pip install` does).

## Python package (pip)

```bash
pip install .            # or: pip install -e .[dev] for the pytest/python-chess dev extras
```

`helpmate` (the root `pyproject.toml`) is the only one of the three
distributions that compiles anything — `helpmate-api` and `helpmate-web`
(`src/packages/api/`, `src/packages/web/`) are plain hatchling wheels with no
C++ involved. Install all three, in dependency order, with `make install` or

```bash
pip install . ./src/packages/api ./src/packages/web
```

(`helpmate-api` depends on `helpmate`, and nothing is published to PyPI yet,
so installing out of order sends pip looking for the name upstream).

Packaging of `helpmate` itself is via scikit-build-core + pybind11 (build
requirements are fetched from PyPI over HTTPS). `pip install` runs **its
own** CMake configure with `-DHELPMATE_PYTHON=ON` — entirely separate from
the plain-CMake `build/` tree — and compiles the same `helpmate_core` C++
sources into the extension module `helpmate._helpmate`. Requires Python ≥
3.9 plus the same CMake ≥ 3.24 and GCC ≥ 13 (export `CC`/`CXX` if your
defaults are older).

Because that configure is separate, it re-runs `FetchContent` — on a machine
with the HTTPS→SSH gitconfig rewrite, pre-seed the dependency sources exactly
as in the offline workflow above, passed through `SKBUILD_CMAKE_ARGS`
(semicolon-separated):

```bash
SKBUILD_CMAKE_ARGS="-DFETCHCONTENT_FULLY_DISCONNECTED=ON;\
-DFETCHCONTENT_SOURCE_DIR_CHESSMG=$PWD/build/_deps/chessmg-src;\
-DFETCHCONTENT_SOURCE_DIR_CATCH2=$PWD/build/_deps/catch2-src;\
-DFETCHCONTENT_SOURCE_DIR_JSON=$PWD/build/_deps/json-src" \
  pip install -e .[dev]
```

(run an ordinary `make build` first so `build/_deps` is populated; optionally
also set `SKBUILD_BUILD_DIR=<dir>` to keep and reuse scikit-build-core's build
tree between installs.)

**Named symptom: `pip install .` hangs with no output and no error**, not
even a passphrase prompt you can answer. This is a different failure mode
from the SSH-prompt case above, and easy to misdiagnose because there is
nothing on stderr to search for. `pip`'s isolated build environment inherits
`HOME`, so a `~/.gitconfig` with `url."git@github.com:".insteadOf =
https://github.com/` still applies to the `FetchContent` clone inside the
pip build — but the clone runs from a subprocess with no attached terminal,
so instead of an SSH passphrase prompt on stdin, it pops a **GUI** passphrase
dialog (`ssh-askpass` or similar). On a headless box, over SSH, or on a CI
runner, that dialog never appears anywhere you can see or answer it, and the
install just sits there indefinitely — no timeout, no error. If `pip
install .` (or `pip install -e .[dev]`) hangs with no output for more than a
few seconds and `build/_deps` isn't already populated, this is almost
certainly it. Fix: bypass the global gitconfig for the install, the same as
the plain-CMake case —

```bash
GIT_CONFIG_GLOBAL=/dev/null pip install .
```

— or pre-seed `build/_deps` and pass `SKBUILD_CMAKE_ARGS` as above so the
pip build's CMake configure never touches the network at all.

Run the Python tests with:

```bash
pytest src/packages/bindings/tests              # fast (~seconds)
pytest src/packages/bindings/tests --run-slow   # + exhaustive KQvk cross-check (~10 min)
```

## Continuous integration

`.github/workflows/ci.yml` runs on every push to `main` and every pull
request: the C++ Release build + fast suite + a gen/probe smoke test, the
Python package install + pytest, and an informational gcovr coverage summary.
`.github/workflows/release.yml` runs on `v*` tags: build, fast tests, and a
GitHub Release with a `helpmate-<tag>-linux-x86_64.tar.gz` binary tarball.

## Troubleshooting

- **"Version mismatch" from gcov during `make coverage`** — your `gcov` doesn't
  match the compiling GCC; pass `GCOV=gcov-13` (default) or the matching
  `gcov-N`.
- **SSH passphrase prompt during configure or `pip install`** — your gitconfig
  rewrites GitHub HTTPS URLs to SSH and `FetchContent` is trying to clone; use
  the pre-fetched `_deps` workflow (`FETCHCONTENT_FULLY_DISCONNECTED` +
  `FETCHCONTENT_SOURCE_DIR_*`, via `SKBUILD_CMAKE_ARGS` for pip) or a one-off
  `GIT_CONFIG_GLOBAL=/dev/null` configure.
- **`pip install .` hangs with no output and no error at all** — not an SSH
  prompt, a *silent* hang: pip's isolated build environment inherits `HOME`,
  so the same gitconfig rewrite above triggers a GUI passphrase dialog
  (`ssh-askpass`) instead of a terminal prompt, and that dialog is invisible
  and unanswerable over SSH or in CI. See [Python package
  (pip)](#python-package-pip) for the full explanation; fix is the same
  `GIT_CONFIG_GLOBAL=/dev/null pip install .`, or pre-seed `build/_deps`.
- **C++20 errors / unknown flags at configure time** — the default compiler is
  too old; export `CXX=/usr/bin/g++-13 CC=/usr/bin/gcc-13` (adjust paths) and
  wipe the build dir before re-configuring.
- **`cmake` too old (< 3.24)** — install a user-local CMake (`pip install
  cmake` or a binary release) and put it first on `PATH`.
- **`make coverage` fails with missing `build/_deps/...-src`** — the coverage
  tree reuses sources from the normal tree; run `make build` (or `make test`)
  once first.
- **Flaky failures when running ctest with `-j`** — known `test_probe.cpp`
  shared-temp-dir race under parallel ctest only; run ctest sequentially (as
  `make test` does).
- **`gcovr: command not found`** — `pip install gcovr` into the Python
  environment on your `PATH`.
