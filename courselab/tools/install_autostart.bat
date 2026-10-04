@echo off
rem Register a logon scheduled task that starts the CourseLab server (no browser).
rem
rem   tools\install_autostart.bat check    print the schtasks command only (no changes)
rem   tools\install_autostart.bat          create the scheduled task (may require admin)
rem
rem Remove it later with: tools\uninstall_autostart.bat
setlocal
set TASKNAME=CourseLab
for %%I in ("%~dp0..") do set LABDIR=%%~fI
set RUNCMD="%LABDIR%\run.bat" no-open

if /i "%~1"=="check" (
    echo schtasks /create /tn "%TASKNAME%" /sc onlogon /f /tr "%RUNCMD%"
    exit /b 0
)

schtasks /create /tn "%TASKNAME%" /sc onlogon /f /tr "%RUNCMD%"
if errorlevel 1 (
    echo [!] failed to create the task. Try running this script as administrator.
    exit /b 1
)
echo Scheduled task "%TASKNAME%" registered: starts CourseLab at logon.
echo Remove it with: tools\uninstall_autostart.bat
endlocal
exit /b 0
