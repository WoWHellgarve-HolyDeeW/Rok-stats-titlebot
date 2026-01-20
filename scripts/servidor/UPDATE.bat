@echo off
setlocal
title RoK Stats - Atualizar Servidor
chcp 65001 >nul
color 0A

REM Detecta automaticamente o caminho do projeto
set "PROJECT=%~dp0..\.."
pushd "%PROJECT%"
set "PROJECT=%CD%"
popd

echo ============================================
echo    ATUALIZAR SERVIDOR ROKSTATS
echo ============================================
echo.
echo Projeto: %PROJECT%
echo.
echo NOTA: Faz git pull manualmente antes!
echo.

cd /d "%PROJECT%"

echo [1/4] A atualizar dependencias Python...
cd /d "%PROJECT%\backend"
call .venv\Scripts\activate.bat
pip install -r requirements.txt --quiet
echo      Dependencias OK!

echo.
echo [2/4] A correr migracoes do banco de dados...
python -m alembic upgrade head
if errorlevel 1 (
    color 0E
    echo AVISO: Migracao pode ter falhado
)

echo.
echo [3/4] A fazer build do frontend...
cd /d "%PROJECT%\frontend-next"
call npm run build
if errorlevel 1 (
    color 0C
    echo ERRO: Falha no build do frontend!
    pause
    exit /b 1
)

echo.
echo [4/4] A importar novos scans...
cd /d "%PROJECT%\RokTracker"

REM Usa o Python do backend venv (que ja esta configurado)
set "PYTHON_EXE=%PROJECT%\backend\.venv\Scripts\python.exe"

if exist "%PYTHON_EXE%" (
    "%PYTHON_EXE%" auto_upload_scans.py
) else (
    echo [SKIP] Python do backend nao encontrado
    echo        Os scans serao importados manualmente depois
)

echo.
echo ============================================
echo    ATUALIZACAO COMPLETA!
echo ============================================
echo.
echo Reinicia o servidor: scripts\servidor\START.bat
echo.
pause
