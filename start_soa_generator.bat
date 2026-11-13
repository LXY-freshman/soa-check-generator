@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if not errorlevel 1 (
    py -3 launcher.py %*
    set "EXIT_CODE=%ERRORLEVEL%"
    if not "%EXIT_CODE%"=="0" pause
    exit /b %EXIT_CODE%
)

where python >nul 2>nul
if not errorlevel 1 (
    python launcher.py %*
    set "EXIT_CODE=%ERRORLEVEL%"
    if not "%EXIT_CODE%"=="0" pause
    exit /b %EXIT_CODE%
)

echo Python 3.10 or newer was not found.
echo Install Python from https://www.python.org/downloads/ and run this file again.
pause
exit /b 2
