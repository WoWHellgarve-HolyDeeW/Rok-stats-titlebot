@echo off
setlocal
title RoK Stats - Verificar Password
chcp 65001 >nul

REM Detecta automaticamente o caminho do projeto
set "PROJECT=%~dp0..\.."
pushd "%PROJECT%"
set "PROJECT=%CD%"
popd

set "BACKEND=%PROJECT%\backend"

echo ============================================
echo   RoK Stats - Verificar Password
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
echo A verificar password...
echo.

cd /d "%BACKEND%"
call .venv\Scripts\activate.bat
python check_password.py %KINGDOM% %PASSWORD%

echo.
pause
