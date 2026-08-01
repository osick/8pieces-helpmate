BUILD ?= build
COVBUILD ?= build-cov
# gcov binary matching the GCC version the coverage build is compiled with (the
# distro's default `gcov` is typically an older system-GCC version and hard-errors
# with "Version mismatch gcc/gcov" against a GCC-13 build); override with
# `make coverage GCOV=/path/to/gcov-N` if your compiler isn't gcc-13.
GCOV ?= gcov-13
.PHONY: configure build test slowtest stress coverage clean jstest \
	install install-dev test-core test-cli test-api test-web test-bindings test-repo test-all \
	lint typecheck format-check format
configure:
	cmake -S . -B $(BUILD)
build: configure
	cmake --build $(BUILD) -j
test: build
	ctest --test-dir $(BUILD) --output-on-failure

# Install all three distributions from this tree, in dependency order:
# helpmate-api requires helpmate, and nothing is on PyPI yet, so installing
# them out of order sends pip looking for the name upstream.
#
# If this hangs with no output and no error: see docs/BUILD.md's entry with
# that exact symptom. Short version: pip's isolated build env inherits HOME,
# so if ~/.gitconfig rewrites https://github.com/ to git@github.com:, CMake
# FetchContent's clone goes over SSH and can pop an invisible GUI passphrase
# dialog. Not hardcoded here because it would also disable legitimate global
# config (proxies, credential helpers); opt in per-invocation instead --
# GNU Make exports command-line variable assignments to the recipe's
# environment automatically, so this needs no plumbing in the recipe itself:
#   make install GIT_CONFIG_GLOBAL=/dev/null
install:
	python -m pip install .
	python -m pip install ./src/packages/api ./src/packages/web

# Same three distributions, with each one's [dev] extra so `make install-dev
# && make test-api` (etc.) has pytest/httpx/playwright available. Same
# GIT_CONFIG_GLOBAL note as `install` applies.
install-dev:
	python -m pip install ".[dev]"
	python -m pip install "./src/packages/api[dev]" "./src/packages/web[dev]"

test-core: build
	$(BUILD)/helpmate_tests "~[slow]"
test-cli: build
	ctest --test-dir $(BUILD) --output-on-failure -R "^cli_"
test-api:
	python -m pytest src/packages/api/tests -v
test-web: jstest
	python -m pytest src/packages/web/tests/ui -v
test-bindings:
	python -m pytest src/packages/bindings/tests -v
test-repo:
	python -m pytest tests/repo -v
test-all: test test-api test-web test-bindings test-repo

lint:
	ruff check .
	node --check $$(git ls-files 'src/packages/web/helpmate_web/static/js/*.js' 'src/packages/web/helpmate_web/static/js/lib/*.js')
typecheck:
	python -m mypy

# Formatting is enforced on the lines a change touches, not on the whole tree:
# reformatting all 4365 lines of existing C++ would be one unreviewable commit
# over the most carefully reviewed code in the project. BASE defaults to the
# merge base with main, which is what CI uses.
BASE ?= $(shell git merge-base origin/main HEAD 2>/dev/null || echo HEAD~1)
format-check:
	git clang-format -q --diff $(BASE) -- '*.cpp' '*.h' | tee /tmp/hm-fmt.diff
	@test ! -s /tmp/hm-fmt.diff || { echo "C++ formatting: run 'make format' and commit"; exit 1; }
format:
	git clang-format $(BASE) -- '*.cpp' '*.h'

# Pure JS helpers (helpmate_web/static/js/lib) via Node's built-in test
# runner. No npm packages. A bare directory arg isn't recursed by `node
# --test` on the Node version this repo targets, so the JS test files are
# globbed explicitly.
jstest:
	node --test src/packages/web/tests/js/*.test.js

# Catch2 cases tagged [slow] (full KPvkp closure generation, KNvkq invariant sweep).
# Excluded from `make test` / ctest by catch_discover_tests' "~[slow]" spec.
slowtest: build
	$(BUILD)/helpmate_tests "[slow]"

# Task 21 regression stress: the oversubscribed KNvkqr root-slice run that is the only
# configuration ever observed to reproduce the crash. Needs taskset (so it cannot be a
# ctest case) and a tables dir already holding the 7 cached sub-slices; see the script
# header for why instrumented/sanitizer builds must NOT be used here.
#   make stress TABLES=/path/to/tables [ITERS=5]
TABLES ?=
ITERS ?= 5
stress: build
	@test -n "$(TABLES)" || { echo "usage: make stress TABLES=<dir with cached sub-slices> [ITERS=n]"; exit 2; }
	tests/stress_oversubscribed_gen.sh "$(TABLES)" $(ITERS)

# Line-coverage report for src/, in its own build dir (build-cov) so the
# normal optimized build is untouched. Reuses the sources FetchContent
# already vendored under $(BUILD)/_deps (run `make build` or `make test`
# at least once first) via FETCHCONTENT_FULLY_DISCONNECTED, so this never
# triggers a network git clone. Requires gcovr (pip install gcovr).
coverage:
	cmake -S . -B $(COVBUILD) -DHELPMATE_COVERAGE=ON -DCMAKE_BUILD_TYPE=Debug \
	  -DFETCHCONTENT_FULLY_DISCONNECTED=ON \
	  -DFETCHCONTENT_SOURCE_DIR_CHESSMG=$(CURDIR)/$(BUILD)/_deps/chessmg-src \
	  -DFETCHCONTENT_SOURCE_DIR_CATCH2=$(CURDIR)/$(BUILD)/_deps/catch2-src \
	  -DFETCHCONTENT_SOURCE_DIR_JSON=$(CURDIR)/$(BUILD)/_deps/json-src
	cmake --build $(COVBUILD) -j2
	ctest --test-dir $(COVBUILD) --output-on-failure
	mkdir -p $(COVBUILD)/coverage
	gcovr --root . --filter 'src/core/' --filter 'src/packages/cli/' \
	  --exclude '.*/tests/.*' --exclude '.*_deps.*' \
	  --gcov-executable $(GCOV) --gcov-ignore-parse-errors=all \
	  --html-details $(COVBUILD)/coverage/index.html \
	  --print-summary $(COVBUILD) | tee $(COVBUILD)/coverage-summary.txt
clean:
	rm -rf $(BUILD) $(COVBUILD)
