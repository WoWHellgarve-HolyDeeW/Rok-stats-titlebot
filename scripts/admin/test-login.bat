@echo off
setlocal
title RoK Stats - Testar Login API
chcp 65001 >nul

REM Detecta automaticamente o caminho do projeto
set "PROJECT=%~dp0..\.."
pushd "%PROJECT%"
set "PROJECT=%CD%"
popd

set "BACKEND=%PROJECT%\backend"

echo ============================================
echo   RoK Stats - Testar Login API
echo ============================================
echo.

if not exist "%BACKEND%\.venv\Scripts\python.exe" (
    echo [ERRO] Backend nao configurado!
    pause
    exit /b 1
)

set /p KINGDOM="Numero do Kingdom (ex: 3167): "
set /p PASSWORD="Password a testar: "

echo.
echo === Teste 1: API Local (localhost:8000) ===
cd /d "%BACKEND%"
call .venv\Scripts\activate.bat
python test_login.py %KINGDOM% %PASSWORD% http://localhost:8000

echo.
echo === Teste 2: API Producao ===
python test_login.py %KINGDOM% %PASSWORD% https://rok.wowhellgarve.com/api

echo.
pause
