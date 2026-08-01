# Package split (v0.7.1) — Design

Date: 2026-08-01
Status: approved by user (brainstorming session 2026-08-01)
Origin: user request after the v0.7.0 release — "the code feels cluttered, in
three different packages: cli client, api server, web server; each should be
deployable separately."
Version: 0.7.1. No GitHub release and no tag; merged and pushed to `main`.

## Why

The repo grew one subsystem at a time and the top level now mixes them: `src/`
holds the C++ core *and* the CLI *and* the Python bindings, `python/` holds a
package that only exists to load the extension, `server/` holds the API, `web/`
holds the dashboard, and `tests/` holds five unrelated suites. A single
`pyproject.toml` builds all of it into one wheel, so there is no way to install
the CLI without pulling in the dashboard, or the API without the CLI.

Nothing is wrong with the code. The boundaries are real but invisible, and the
packaging does not reflect them.

## Decisions taken in the session

1. **Separate installable artifacts**, not containers and not a cosmetic move.
   Three Python distributions, each `pip install`-able on its own.
2. **The CLI ships in a wheel.** `pip install helpmate` puts the `helpmate`
   binary on PATH; no C++ toolchain needed on the target machine.
3. **Tests colocate with their package.** A package is a unit you can build and
   verify without the rest of the repo.

## Distributions

| Distribution | Contents | Depends on |
|---|---|---|
| `helpmate` | C++ core library, `helpmate` CLI binary, pybind11 extension, `helpmate` Python package | — |
| `helpmate-api` | `helpmate_server`: the FastAPI app, storage layer, and the `helpmate-tables` CLI | `helpmate`, `fastapi`, `uvicorn`, `huggingface_hub` |
| `helpmate-web` | `helpmate_web`: the dashboard as package data, plus a `static_dir()` accessor | — |

`helpmate-api` depends on `helpmate>=0.7.1,<0.8` — a compatible range, not an
exact pin, so a patch to one does not force a reinstall of the other.

Because nothing is published to PyPI yet, that dependency must be satisfied
from the local tree: `helpmate` has to be installed **before** `helpmate-api`,
or pip will go looking for the name on PyPI and either fail or, worse, install
an unrelated project that happens to hold it. The `make install` target
enforces the order, and the documented command lists the paths in order for the
same reason.

The core, the CLI and the bindings stay in **one** distribution. They are one
CMake project and one compilation of the core; splitting them would mean either
building the core twice or publishing a shared-library package for both to link
against. Neither buys anything today.

## Tree

```
CMakeLists.txt                     thin: project(), FetchContent, add_subdirectory x3
VERSION                            single source of truth for the version
pyproject.toml                     builds `helpmate` (owns the CMake project)
Makefile                           per-package targets
docs/  tools/  specs/              unchanged

src/core/
  CMakeLists.txt                   helpmate_core + Catch2 suite registration
  version.h.in                     configured from ${PROJECT_VERSION}
  chess/ indexing/ format/ generator/ probe/
  tests/                           the 20 Catch2 test_*.cpp files

src/packages/cli/
  CMakeLists.txt                   `helpmate` target, install rule, the CLI ctest cases
  main.cpp
  tests/                           mk_legacy_table.cpp, assert_absent.cmake

src/packages/bindings/
  CMakeLists.txt                   pybind11 module
  pymodule.cpp
  helpmate/__init__.py             the Python package (was python/helpmate)
  tests/                           was tests/python

src/packages/api/
  pyproject.toml                   helpmate-api (hatchling)
  helpmate_server/                 was server/helpmate_server
  tests/                           was tests/server

src/packages/web/
  pyproject.toml                   helpmate-web (hatchling)
  helpmate_web/__init__.py         static_dir()
  helpmate_web/static/             was web/ (index.html, css/, js/, vendor/)
  tests/js/                        was tests/js
  tests/ui/                        was tests/ui

tests/repo/                        cross-package invariants only (see Versioning)
```

Every move uses `git mv`, so history follows the files.

The dashboard's own URLs (`/css/app.css`, `/js/explorer.js`,
`/vendor/cm-chessboard/...`) are unchanged: they are absolute paths under the
mount root, and the mount root becomes `helpmate_web/static`. No HTML, CSS or
JS source needs editing for the move — only the test files' relative imports
and the `.gitignore` negations.

## CMake

The root `CMakeLists.txt` keeps only what is genuinely global: `project()`, the
C++ standard, the `Threads` and `FetchContent` setup for chessmg/Catch2/json,
the `HELPMATE_PYTHON` and `HELPMATE_COVERAGE` options, `enable_testing()`, and
three `add_subdirectory()` calls. Everything else moves to the package that
owns it:

- `src/core/CMakeLists.txt` — `helpmate_core`, its sources and include dirs, the
  coverage flags, the `helpmate_tests` executable and `catch_discover_tests`.
- `src/packages/cli/CMakeLists.txt` — the `helpmate` executable, the install
  rule, `mk_legacy_table`, and all 31 CLI `add_test` / `set_tests_properties`
  declarations.
- `src/packages/bindings/CMakeLists.txt` — the `pybind11_add_module` block,
  guarded by `HELPMATE_PYTHON` as today.

Two CMake-level improvements the split makes natural, both of which remove a
hand-maintained duplicate of the version:

- **`src/version.h` becomes `src/core/version.h.in`**, configured from
  `${PROJECT_VERSION}`. The literal disappears.
- **The `cli_version` ctest regex is built from `${PROJECT_VERSION}`** instead
  of hardcoding `helpmate 0\.7\.0`, which has had to be edited by hand on every
  release so far.

## Shipping the CLI in the wheel

```cmake
install(TARGETS helpmate RUNTIME DESTINATION ${SKBUILD_SCRIPTS_DIR})
```

scikit-build-core sets `SKBUILD_SCRIPTS_DIR`; a binary installed there lands in
the environment's `bin/` and goes on PATH. The plain
`install(TARGETS helpmate RUNTIME DESTINATION bin)` rule stays for
`cmake --install`, guarded so the two do not collide: when `SKBUILD_SCRIPTS_DIR`
is defined we are building a wheel and use it, otherwise `bin`.

This is still a source build at install time — there are no prebuilt wheels, so
`pip install helpmate` compiles the core on the target machine. Publishing
binary wheels per platform is a separate, unscheduled rung.

## How the API finds the dashboard

`create_app` resolves the static root in a fixed order and stops at the first
hit:

1. an explicit `--web-root DIR` — a hard error if it is not a directory, since
   the user asked for it by name;
2. `helpmate_web.static_dir()`, if `helpmate_web` imports — the installed-package
   answer, and correct in a wheel, an editable install and a container alike;
3. the source-checkout path `<repo>/src/packages/web/helpmate_web/static`;
4. nothing — the API runs without a dashboard, which it already supports.

`--no-web` skips the mount entirely.

This replaces the current `parents[1]` / `parents[2]` filesystem probe, which
guesses at two layouts and silently serves nothing when it guesses wrong.

## Versioning

One `VERSION` file at the repo root holds the version. It is read by:

- CMake, into `project(... VERSION ...)`, hence into `version.h` and the
  `cli_version` regex;
- all three `pyproject.toml` files — which keep a literal, because a
  dynamic-version plugin is a dependency and a failure mode for a two-line
  benefit.

The literals are held honest by a test rather than by discipline:
`tests/repo/test_version_consistency.py` asserts that `VERSION`, the three
`pyproject.toml` versions, `helpmate.__version__`, `helpmate_server.__version__`
and `helpmate --version` all agree. This is the one suite that is deliberately
**not** colocated: it is a statement about the repo, not about any one package.

Releases stay lockstep — one version, one CHANGELOG, one tag. Independent
per-package versioning is not needed while all three ship together, and it can
be adopted later without undoing anything here.

## Migration surface

Beyond the moves themselves:

- **`.gitignore`.** The generic Python `lib/` rule needs its two negations
  repointed to `src/packages/web/helpmate_web/static/js/lib/` and
  `.../static/vendor/cm-chessboard/lib/`. This exact rule has already excluded
  deliverables twice in this project; if it is wrong, a fresh clone serves a
  dashboard whose board never loads, and nothing fails locally.
- **Install instructions change.** `pip install ".[server]"` no longer works,
  because the server is a different distribution and `helpmate-api` is not on
  PyPI. The documented command becomes
  `pip install . ./src/packages/api ./src/packages/web`, wrapped in a
  `make install` target. README, `docs/USAGE.md`, `docs/BUILD.md` and `ci.yml`
  all carry the old command.
- **Test-dependency extras.** The single `dev` extra splits: `helpmate[dev]`
  gets `pytest` and `chess`, `helpmate-api[dev]` gets `pytest` and `httpx`,
  `helpmate-web[dev]` gets `pytest` and `playwright`.
- **Makefile.** `jstest`'s glob, the coverage `--filter 'src/'` (still correct),
  and new `test-core` / `test-cli` / `test-api` / `test-web` targets.
- **`tests/ui/conftest.py`** imports `helpmate` and spawns
  `helpmate_server.main:_app_for_tests`; both keep working, but the fixture's
  own path assumptions need checking.
- **`tools/api_smoke.py`** and the docs reference paths that move.

## Testing

No new behaviour is introduced, so the test suites are the specification: they
must all pass unchanged in content from their new locations, with the same case
counts.

- **117 ctest cases, exactly** — 86 Catch2 (`catch_discover_tests`) plus 31 CLI
  cases. A different total means a test was lost in the CMake split, which is
  the single most likely silent failure of this work.
- **86 C++ cases** from `helpmate_tests "~[slow]"`.
- **75 Python tests** across the bindings and API suites.
- **29 Node tests**, **11 Playwright tests**.
- **New:** the version-consistency test.

**Install verification, in a clean virtualenv** — this is what "separately
deployable" means, so it is checked and not assumed:

1. `pip install .` → `helpmate --version` prints the VERSION file's version, and
   `import helpmate` works.
2. `pip install ./src/packages/api` → `helpmate-server --help` works, and the
   server starts and answers `/v1/health` with **no** `helpmate_web` installed,
   serving no dashboard and saying so rather than failing.
3. `pip install ./src/packages/web` → the same server now serves the dashboard
   at `/`, located through `helpmate_web.static_dir()` and not through a path
   guess.
4. `helpmate-server --web-root <dir>` overrides, and `--no-web` suppresses.

## Out of scope

Containers and compose files; CORS and a configurable API base URL in the
dashboard (both only matter once the web is served from a different origin);
publishing to PyPI; prebuilt binary wheels; splitting the C++ core into its own
distribution; independent per-package versioning.

## Risks

- **The CMake split loses a test silently.** Mitigated by pinning the exact
  case count, and by moving declarations verbatim rather than rewriting them.
- **`.gitignore` excludes moved deliverables.** Mitigated by verifying against
  a fresh clone (`git ls-files` on the new paths), not against the working tree.
- **`SKBUILD_SCRIPTS_DIR` behaves differently across scikit-build-core
  versions.** Mitigated by the clean-venv install check, which is the only way
  to see it.
- **Churn against the v0.7.0 release.** Every path in the just-published docs
  changes. The docs sweep is part of the work, not a follow-up.
