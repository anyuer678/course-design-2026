@echo off
rem B28-bi-dashboard one-click entry. Body is pure ASCII on purpose:
rem cmd re-reads this file by byte offset, so multi-byte text here can make it
rem resume in the middle of a line. Chinese hints are printed by say.py / step6.py.
rem No multi-line parenthesized block near the end: on this machine a trailing
rem "if (...) ... exit /b 0" block made every run print
rem "The process cannot access the file because it is being used by another process."
rem with exit code still 0. Step 6 branching now lives in step6.py.
chcp 65001 >nul
setlocal
cd /d %~dp0
set PYTHONUTF8=1

where python >nul 2>nul
if errorlevel 1 (
    echo [!] python not found in PATH. Install Python 3.10+ first.
    exit /b 1
)

echo [1/6] environment check
python --version
python -c "import sqlite3, sys; from bi import warehouse; from bi import sql_policy; from mining import clean; from kg import viz; from sec32 import audit; print('      Python', sys.version.split()[0], '| SQLite', sqlite3.sqlite_version); print('      reuse B26 mining + B27 kg + B32 sec32.audit')"
if errorlevel 1 exit /b 1

echo.
echo [2/6] unit tests via unittest discover
python -m unittest discover -s tests
if errorlevel 1 exit /b 1

echo.
echo [3/6] unit tests via direct file run (dual entry, same count expected)
python tests\test_b28.py
if errorlevel 1 exit /b 1

echo.
echo [4/6] policy checks: SQL concat sites, metric lineage, reconciliation
python -c "from bi import sql_policy as P, lineage as L, metrics as M, warehouse as W; c, d = W.build(); r = M.compute(c, d); print('      unregistered SQL concat sites:', P.problems() or 'none'); print('      lineage problems:', L.problems() or 'none'); print('      metric reconciliation:', M.mismatches(r) or 'all equal'); print('      scanner has teeth:', P.prove_scanner_has_teeth())"
if errorlevel 1 exit /b 1

echo.
echo [5/6] demo: six sections, numbers computed live
python demo.py
if errorlevel 1 exit /b 1

echo.
echo [6/6] manual walkthrough list, then the local server
echo       pass no-server to stop before starting it
python step6.py %*
if errorlevel 1 exit /b 1

echo.
echo Done. Tests, policy checks and demo ran in memory; nothing new was left here.
endlocal
exit /b 0
