#!/usr/bin/env bash
# run.sh —— B8-mini-shell 一键入口（Linux/WSL 侧）：编译 → 双入口自测 → 演示。
# Windows 侧入口是 run.bat：它只负责把这里的三步交给 WSL Ubuntu-24.04 执行。
set -e -o pipefail
cd "$(dirname "$0")"
mkdir -p build

echo "[1/3] compile msh with gcc -std=c11 -O2 -Wall -Wextra"
gcc -std=c11 -O2 -Wall -Wextra -o build/msh src/msh.c

echo
echo "[2/3] self-test: both entries must report the same count"
if ! discover_out=$(python3 -m unittest discover -s tests 2>&1); then
    printf '%s\n' "$discover_out"
    exit 1
fi
if ! direct_out=$(python3 tests/test_msh.py 2>&1); then
    printf '%s\n' "$direct_out"
    exit 1
fi
# 计时行去掉（sed）：两次运行日志才能逐字一致；计数行留着当"双入口同数"的证据
echo "  [discover entry] $(printf '%s\n' "$discover_out" | sed 's/ in [0-9.]*s$//' | grep -E '^(Ran|OK|FAILED)' | tr '\n' ' ')"
echo "  [direct entry]   $(printf '%s\n' "$direct_out" | sed 's/ in [0-9.]*s$//' | grep -E '^(Ran|OK|FAILED)' | tr '\n' ' ')"

echo
echo "[3/3] demo (six sections, outcomes measured for real)"
python3 demo.py

echo
echo "Done. Interactive use: ./build/msh   (Ctrl-D 退出)"
