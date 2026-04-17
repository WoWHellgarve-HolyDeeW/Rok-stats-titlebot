@echo off
setlocal
title RoK Stats - SERVIDOR PRODUCAO
chcp 65001 >nul

REM Detecta automaticamente o caminho do projeto
set "PROJECT=%~dp0..\.."
pushd "%PROJECT%"
set "PROJECT=%CD%"
popd

set "BACKEND=%PROJECT%\backend"
set "FRONTEND=%PROJECT%\frontend-next"

REM === CONFIGURACAO ===
set "API_PORT=8000"
set "WEB_PORT=3000"
set "DATABASE_URL="
set "INGEST_TOKEN="

echo ============================================
echo   RoK Stats Hub - SERVIDOR PRODUCAO
echo ============================================
echo.
echo Projeto: %PROJECT%
echo.

REM Verificar setup
if not exist "%BACKEND%\.venv\Scripts\uvicorn.exe" (
    echo [ERRO] Backend nao configurado!
    echo        Corre primeiro: scripts\servidor\SETUP.bat
    pause
    exit /b 1
)

if not exist "%FRONTEND%\.next" (
    echo [ERRO] Frontend nao buildado!
    echo        Corre primeiro: scripts\servidor\SETUP.bat
    pause
    exit /b 1
)

echo [1/2] Iniciando Backend (API)...
start "rok-backend" cmd /k "cd /d %BACKEND% && call .venv\Scripts\activate.bat && set INGEST_TOKEN=%INGEST_TOKEN% && set DATABASE_URL=%DATABASE_URL% && .venv\Scripts\uvicorn.exe app.main:app --host 0.0.0.0 --port %API_PORT%"

timeout /t 3 /nobreak >nul

echo [2/2] Iniciando Frontend (Website)...
start "rok-frontend" cmd /k "cd /d %FRONTEND% && npm run start -- -p %WEB_PORT% -H 0.0.0.0"

echo.
echo ============================================
echo        SERVIDOR ONLINE!
echo ============================================
echo.
echo   Website:    http://localhost:%WEB_PORT%
echo   API:        http://localhost:%API_PORT%
echo   API Docs:   http://localhost:%API_PORT%/docs
echo.
echo   Abriram 2 janelas - NAO FECHAR!
echo ============================================
echo.
endlocal
pause
