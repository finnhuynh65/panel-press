@echo off
setlocal

rem Run from the directory containing this file, even when launched by double-click.
cd /d "%~dp0"

if not defined PORT set "PORT=8080"
if not defined PYTHON_BIN set "PYTHON_BIN=python"

"%PYTHON_BIN%" --version >nul 2>&1
if errorlevel 1 (
    echo Python executable not found: %PYTHON_BIN%
    echo Install Python 3 and ensure it is on PATH, or set PYTHON_BIN to its full path.
    pause
    exit /b 1
)

rem Avoid starting a second server on the same port.
netstat -ano -p TCP | findstr /r /c:":%PORT% .*LISTENING" >nul 2>&1
if not errorlevel 1 (
    echo Port %PORT% is already in use.
    echo Set PORT to another value, for example: set PORT=8081 ^&^& start.bat
    pause
    exit /b 1
)

echo Starting Panel Press at http://127.0.0.1:%PORT%/
"%PYTHON_BIN%" webapp.py
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
    echo.
    echo The server exited with code %EXIT_CODE%.
    pause
)

exit /b %EXIT_CODE%
