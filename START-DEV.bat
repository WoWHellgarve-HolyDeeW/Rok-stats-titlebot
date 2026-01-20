@echo off
setlocal
title RoK Stats - Desenvolvimento Local
chcp 65001 >nul

REM Detecta automaticamente o caminho do projeto
set "PROJECT=%~dp0"
if "%PROJECT:~-1%"=="\" set "PROJECT=%PROJECT:~0,-1%"

set "BACKEND=%PROJECT%\backend"
set "FRONTEND=%PROJECT%\frontend-next"
set "ROKTRACKER=%PROJECT%\RokTracker"

REM === CONFIGURACAO ===
set "INGEST_TOKEN="
set "DATABASE_URL="
set "PYTHON311=python"

REM Bots (1=ligar, 0=desligar)
set "START_TITLE_BOT=0"

echo ============================================
echo   RoK Stats Hub - DESENVOLVIMENTO LOCAL
echo ============================================
echo.
echo Projeto: %PROJECT%
echo.

REM === Backend venv ===
if not exist "%BACKEND%\.venv" (
    echo [SETUP] Criando venv do backend...
    python -m venv "%BACKEND%\.venv"
    "%BACKEND%\.venv\Scripts\python.exe" -m pip install --upgrade pip >nul
    "%BACKEND%\.venv\Scripts\python.exe" -m pip install -r "%BACKEND%\requirements.txt"
)

REM === Frontend deps ===
if not exist "%FRONTEND%\node_modules" (
    echo [SETUP] Instalando deps do frontend...
    pushd "%FRONTEND%"
    call npm install
    popd
)

echo [1/3] Iniciando Backend...
start "rok-backend" cmd /k "cd /d %BACKEND% && call .venv\Scripts\activate.bat && set INGEST_TOKEN=%INGEST_TOKEN% && set DATABASE_URL=%DATABASE_URL% && uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload"

timeout /t 3 /nobreak >nul

echo [2/3] Iniciando Frontend (dev mode)...
start "rok-frontend" cmd /k "cd /d %FRONTEND% && set NEXT_PUBLIC_API_URL=http://localhost:8000 && npm run dev"

if "%START_TITLE_BOT%"=="1" (
    echo [3/3] Iniciando Title Bot...
    start "rok-title-bot" cmd /k "cd /d %ROKTRACKER% && %PYTHON311% -u title_bot.py"
) else (
    echo [3/3] Title Bot desativado
)

echo.
echo ============================================
echo   AMBIENTE DE DESENVOLVIMENTO INICIADO!
echo ============================================
echo.
echo   Backend:     http://localhost:8000
echo   Frontend:    http://localhost:3000
echo   API docs:    http://localhost:8000/docs
echo.
echo   Para fechar: fecha as janelas abertas
echo ============================================
echo.
endlocal
pause
