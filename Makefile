BUILD ?= build
COVBUILD ?= build-cov
.PHONY: configure build test coverage clean
configure:
	cmake -S . -B $(BUILD)
build: configure
	cmake --build $(BUILD) -j
test: build
	ctest --test-dir $(BUILD) --output-on-failure

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
	cmake --build $(COVBUILD) -j
	ctest --test-dir $(COVBUILD) --output-on-failure
	gcovr --root . --filter 'src/' --exclude '.*_deps.*' \
	  --html-details $(COVBUILD)/coverage/index.html \
	  --print-summary $(COVBUILD) | tee $(COVBUILD)/coverage-summary.txt
clean:
	rm -rf $(BUILD) $(COVBUILD)
