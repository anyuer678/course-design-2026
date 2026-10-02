@echo off
rem B14-java-paint one-click entry. Body is pure ASCII on purpose (PLAN section 6):
rem cmd re-reads this file by byte offset, so multi-byte text here makes it resume
rem in the middle of a line (this project is where that pitfall was first recorded:
rem a Chinese line before a goto made cmd run "'adless' is not recognized").
rem Build output goes to %TEMP%, so the project directory keeps no build residue.
chcp 65001 >nul
setlocal
cd /d %~dp0
set JAVA_FLAGS=-Dfile.encoding=UTF-8 -Dstdout.encoding=UTF-8
set BUILD=%TEMP%\b14-java-paint-build

where javac >nul 2>nul
if errorlevel 1 echo [!] javac not found in PATH. Install JDK 17 or newer first.
if errorlevel 1 exit /b 1

if exist "%BUILD%" rmdir /s /q "%BUILD%"
mkdir "%BUILD%\classes" "%BUILD%\test-classes"

echo [1/4] compile (release 17, UTF-8 sources)
javac -version 2>&1
dir /s /b src\main\java\*.java > "%BUILD%\sources-main.txt"
javac --release 17 -encoding UTF-8 -d "%BUILD%\classes" @"%BUILD%\sources-main.txt"
if errorlevel 1 exit /b 1
dir /s /b src\test\java\*.java > "%BUILD%\sources-test.txt"
javac --release 17 -encoding UTF-8 -cp "%BUILD%\classes" -d "%BUILD%\test-classes" @"%BUILD%\sources-test.txt"
if errorlevel 1 exit /b 1
echo       compiled into %BUILD%

echo.
echo [2/4] headless self-test (no window, java.awt.headless=true)
java -Djava.awt.headless=true %JAVA_FLAGS% -cp "%BUILD%\classes;%BUILD%\test-classes" paint.PaintTests
if errorlevel 1 exit /b 1

echo.
echo [3/4] offscreen demo: draw three shapes, undo, redo, count pixels, write PNG to temp
java -Djava.awt.headless=true %JAVA_FLAGS% -cp "%BUILD%\classes" paint.App --demo
if errorlevel 1 exit /b 1

if /i "%~1"=="no-gui" goto :skip_gui
echo.
echo [4/4] opening the paint window. Manual checklist is in README (section: walkthrough).
echo       Close the window when done; unsaved changes trigger a confirmation dialog.
start /wait "" java %JAVA_FLAGS% -cp "%BUILD%\classes" paint.App
echo.
echo Done. Saved documents and exported PNGs go to the data directory.
endlocal
exit /b 0

:skip_gui
echo.
echo [4/4] skipped on purpose (no-gui). Run "run.bat" to open the window.
echo Done. Nothing was written into this folder; the build lives in %BUILD%.
endlocal
exit /b 0
