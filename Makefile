BUILD ?= build
COVBUILD ?= build-cov
# gcov binary matching the GCC version the coverage build is compiled with (the
# distro's default `gcov` is typically an older system-GCC version and hard-errors
# with "Version mismatch gcc/gcov" against a GCC-13 build); override with
# `make coverage GCOV=/path/to/gcov-N` if your compiler isn't gcc-13.
GCOV ?= gcov-13
.PHONY: configure build test slowtest stress coverage clean
configure:
	cmake -S . -B $(BUILD)
build: configure
	cmake --build $(BUILD) -j
test: build
	ctest --test-dir $(BUILD) --output-on-failure

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
	gcovr --root . --filter 'src/' --exclude '.*_deps.*' \
	  --gcov-executable $(GCOV) --gcov-ignore-parse-errors=all \
	  --html-details $(COVBUILD)/coverage/index.html \
	  --print-summary $(COVBUILD) | tee $(COVBUILD)/coverage-summary.txt
clean:
	rm -rf $(BUILD) $(COVBUILD)
