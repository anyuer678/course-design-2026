# B9-os-sim
CXX ?= g++
CXXFLAGS ?= -std=c++17 -O2 -Wall -Wextra -static -pthread -Iinclude
HDRS := $(wildcard include/ossim/*.hpp)

all: build/tests.exe build/os-sim.exe

build/tests.exe: tests/test_ossim.cpp $(HDRS)
	@mkdir -p build
	$(CXX) $(CXXFLAGS) tests/test_ossim.cpp -o build/tests.exe

build/os-sim.exe: src/main.cpp $(HDRS)
	@mkdir -p build
	$(CXX) $(CXXFLAGS) src/main.cpp -o build/os-sim.exe

test: build/tests.exe
	./build/tests.exe

demo: build/os-sim.exe
	./build/os-sim.exe

clean:
	@rm -rf build

.PHONY: all test demo clean
