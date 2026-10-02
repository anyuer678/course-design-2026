# demo/Makefile —— 演示用：全量 -> up to date -> 改源码增量
# 产物统一进 build/，这样 clean 一条命令就能还原（不会在 demo/ 里留东西）。
all: build/greet.exe

build/greet.exe: src/greet.cpp
	if not exist build mkdir build
	g++ -std=c++17 -O2 -o build/greet.exe src/greet.cpp

run: build/greet.exe
	build\greet.exe

.PHONY: all run clean
clean:
	if exist build rmdir /s /q build
