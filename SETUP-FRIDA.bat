@echo off
REM ============================================================
REM  RoK Stats Hub - Frida runtime setup
REM  Sets up the Python env and dependencies for the Frida stack.
REM  by WoWHellgarve-HolyDeeW
REM ============================================================
setlocal EnableDelayedExpansion
title RoK Stats Hub - Frida Setup
color 0E
pushd "%~dp0"

echo.
echo   RoK Stats Hub - Frida runtime setup
echo   by WoWHellgarve-HolyDeeW
echo   ------------------------------------------
echo.

REM --- Check Python 3.12 ---
where py >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python launcher 'py' not found. Install Python 3.12 from https://www.python.org/downloads/
    pause
    exit /b 1
)

py -3.12 -c "import sys; print(sys.version)" >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python 3.12 not installed. Install it from https://www.python.org/downloads/
    pause
    exit /b 1
)
echo [OK] Python 3.12 detected.

REM --- Create backend venv ---
if not exist "backend\.venv\Scripts\python.exe" (
    echo [..] Creating backend virtual environment (backend\.venv)
    py -3.12 -m venv backend\.venv
    if errorlevel 1 (
        echo [ERROR] Failed to create venv.
        pause
        exit /b 1
    )
)
echo [OK] backend\.venv ready.

set "PY=%CD%\backend\.venv\Scripts\python.exe"

echo [..] Upgrading pip
"%PY%" -m pip install --upgrade pip >nul

echo [..] Installing backend requirements
"%PY%" -m pip install -r backend\requirements.txt
if errorlevel 1 (
    echo [ERROR] pip install failed.
    pause
    exit /b 1
)

echo [..] Installing Frida tools
"%PY%" -m pip install frida frida-tools
if errorlevel 1 (
    echo [ERROR] Failed to install frida.
    pause
    exit /b 1
)

echo.
echo   ============================================
echo    Frida runtime environment is ready.
echo.
echo    Next steps:
echo      1. Start an Android emulator (LDPlayer 9 recommended).
echo      2. Push frida-server into the emulator and run it on port 27042.
echo         Download: https://github.com/frida/frida/releases
echo      3. Forward the port:    adb forward tcp:27142 tcp:27042
echo      4. Launch Rise of Kingdoms inside the emulator.
echo      5. Run the backend stack (SETUP.bat or docker compose up).
echo      6. Run START-FRIDA.bat to attach.
echo.
echo    Full walkthrough: docs\title-bot-live-session.md
echo   ============================================
echo.
echo   by WoWHellgarve-HolyDeeW
echo.
pause
popd
endlocal
