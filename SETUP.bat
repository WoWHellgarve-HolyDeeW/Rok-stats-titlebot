@echo off
REM ============================================
REM   ROK STATS HUB - QUICK SETUP (Windows)
REM ============================================
REM This script will set up everything for you!
REM Run this as Administrator if you have issues.
REM ============================================

echo.
echo ============================================
echo   ROK STATS HUB - QUICK SETUP
echo ============================================
echo.

REM Check Python
echo [1/6] Checking Python...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Python not found!
    echo Please install Python 3.11+ from https://www.python.org/downloads/
    echo Make sure to check "Add to PATH" during installation!
    pause
    exit /b 1
)
echo       Python OK!

REM Check Node.js
echo [2/6] Checking Node.js...
node --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Node.js not found!
    echo Please install Node.js 20+ from https://nodejs.org/
    pause
    exit /b 1
)
echo       Node.js OK!

REM Check Tesseract
echo [3/6] Checking Tesseract OCR...
tesseract --version >nul 2>&1
if %errorlevel% neq 0 (
    echo WARNING: Tesseract OCR not found!
    echo The scanner will not work without it.
    echo Download from: https://github.com/UB-Mannheim/tesseract/wiki
    echo.
)
if %errorlevel% equ 0 (
    echo       Tesseract OK!
)

REM Setup Backend
echo [4/6] Setting up Backend...
cd backend
if not exist .venv (
    python -m venv .venv
)
call .venv\Scripts\activate
pip install -r requirements.txt -q
if not exist .env (
    copy .env.example .env >nul
    echo       Created backend\.env - EDIT THIS FILE with your secret keys!
)
alembic upgrade head
cd ..
echo       Backend OK!

REM Setup Frontend
echo [5/6] Setting up Frontend...
cd frontend-next
if not exist node_modules (
    call npm install
)
if not exist .env.local (
    copy .env.example .env.local >nul
    echo       Created frontend-next\.env.local
)
cd ..
echo       Frontend OK!

REM Setup Scanner
echo [6/6] Setting up Scanner...
cd RokTracker
if not exist venv (
    python -m venv venv
)
call venv\Scripts\activate
pip install -r requirements_win64.txt -q
if not exist api_config.json (
    copy api_config.example.json api_config.json >nul
    echo       Created RokTracker\api_config.json - EDIT with your kingdom number!
)
if not exist bot_config.json (
    copy bot_config.example.json bot_config.json >nul
)
cd ..
echo       Scanner OK!

echo.
echo ============================================
echo   SETUP COMPLETE!
echo ============================================
echo.
echo IMPORTANT - Edit these files before running:
echo   1. backend\.env          - Change SECRET_KEY and INGEST_TOKEN
echo   2. RokTracker\api_config.json - Change kingdom_numbers
echo.
echo To start the application, run: START-DEV.bat
echo.
echo For more help, read README.md
echo.
pause
