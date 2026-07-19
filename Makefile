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
