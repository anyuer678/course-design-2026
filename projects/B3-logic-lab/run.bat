@echo off
rem B3-logic-lab one-click entry. Body is pure ASCII on purpose (PLAN section 6):
rem cmd re-reads this file by byte offset, so multi-byte text here can make it
rem resume in the middle of a line. Chinese output comes from the Python files.
chcp 65001 >nul
setlocal
cd /d %~dp0
set PYTHONUTF8=1

python -c "import shutil,sys; sys.exit(0 if shutil.which('python') else 1)"
if errorlevel 1 echo [!] python not found in PATH. Install Python 3.10+ first.
if errorlevel 1 exit /b 1

echo [1/2] unit tests (36: lexer / parser / truth tables / normal forms / relations)
python -m unittest discover -s tests
if errorlevel 1 exit /b 1

echo.
echo [2/2] demo (5 sections: parsing, normal forms, equivalence, closures, cross-check)
python demo.py
if errorlevel 1 exit /b 1

echo.
echo Done. See README.md for interactive examples and G2 exercises.
endlocal
exit /b 0
