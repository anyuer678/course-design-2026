@echo off
rem B15-B20 dorm-repair entry point: requirements checks, model tests, prototype, Java platform,
rem and the layered pipeline (shrink / consequence measurement / mutation self-check).
rem This file stays 100 percent ASCII on purpose: cmd re-reads batch files by byte offset,
rem and multi-byte text in the body can make it resume mid-line and try to execute half a
rem Chinese sentence (exit code still 0). All human-facing messages live in say.py.
rem Three arguments are understood: "no-web" skips the browser step, "pipeline" runs only
rem tools/pipeline.py (the whole layer chain in one command), "gate" runs the QA gate decision.
chcp 65001 >nul
setlocal
cd /d %~dp0
set PYTHONUTF8=1
set B16_PORT=8010

where python >nul 2>nul || (python say.py nopython & exit /b 1)

rem Note: inside a parenthesized block cmd expands %ERRORLEVEL% when it parses the block,
rem not when it reaches the line, so "exit /b %ERRORLEVEL%" would leak the previous status.
rem The explicit || form is what actually propagates a non-zero pipeline result.
if /i "%~1" == "gate" (
    python say.py gate
    python tools/quality_gate.py || exit /b 1
    exit /b 0
)

if /i "%~1" == "pipeline" (
    python say.py pipeline
    python tools/pipeline.py || exit /b 1
    exit /b 0
)

python say.py step1
python --version
python -c "import csv, dataclasses, enum, unittest, json; print('      stdlib only: csv, enum, dataclasses, json, unittest')"

echo.
python say.py step2
python checks/check_docs.py || exit /b 1

echo.
python say.py step3
python tools/export_contract.py --check || exit /b 1
python tools/export_verdict_table.py --check || exit /b 1
python tools/walkthrough_pack.py --check || exit /b 1
python checks/check_arch.py || exit /b 1

echo.
python say.py step4
python -m unittest discover -s tests || exit /b 1

echo.
python say.py step5
python demo.py || exit /b 1

echo.
python say.py step6
python tools/java_build.py || exit /b 1

echo.
python say.py step7
python tools/pipeline.py --only pm --only qa --only shrink --only consequences --only mutation || exit /b 1

if /i "%~1" == "no-web" (
    echo.
    python say.py skip8
    echo.
    python say.py done1
    python say.py done2
    echo.
    python say.py done4
    exit /b 0
)

echo.
python say.py step8
python say.py walk
python -m prototype.server --port %B16_PORT%

echo.
python say.py done1
python say.py done2
echo.
python say.py done4
endlocal
