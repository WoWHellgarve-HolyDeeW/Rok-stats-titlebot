@echo off
setlocal
title RoK Stats - Reset Password
chcp 65001 >nul

REM Detecta automaticamente o caminho do projeto
set "PROJECT=%~dp0..\.."
pushd "%PROJECT%"
set "PROJECT=%CD%"
popd

set "BACKEND=%PROJECT%\backend"

echo ============================================
echo   RoK Stats - Reset Password
echo ============================================
echo.

if not exist "%BACKEND%\.venv\Scripts\python.exe" (
    echo [ERRO] Backend nao configurado!
    pause
    exit /b 1
)

:ask_kingdom
set /p KINGDOM="Numero do Kingdom (ex: 3167): "

if "%KINGDOM%"=="" (
    echo [ERRO] Tens de introduzir um numero!
    goto ask_kingdom
)

echo.
echo A resetar password para Kingdom %KINGDOM%...
echo.

cd /d "%BACKEND%"
call .venv\Scripts\activate.bat
python reset_kingdom_password.py %KINGDOM%

echo.
pause
