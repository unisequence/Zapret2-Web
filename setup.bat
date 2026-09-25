@echo off
setlocal
cd /d "%~dp0"

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\setup_windows.ps1"
set "result=%ERRORLEVEL%"

if not "%result%"=="0" (
    echo.
    echo Setup did not complete successfully. See the message above.
    pause
)

exit /b %result%
