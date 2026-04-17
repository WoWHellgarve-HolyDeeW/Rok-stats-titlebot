@echo off
setlocal
title RoK Stats - Upload Scans Manual
chcp 65001 >nul

REM Detecta automaticamente o caminho do projeto
set "PROJECT=%~dp0..\.."
pushd "%PROJECT%"
set "PROJECT=%CD%"
popd

set "ROKTRACKER=%PROJECT%\RokTracker"

echo ============================================
echo   RoK Stats - Upload Scans Manual
echo ============================================
echo.
echo Este script importa todos os CSVs de scans
echo que ainda nao foram enviados para a API.
echo.

cd /d "%ROKTRACKER%"

if exist "venv\Scripts\python.exe" (
    venv\Scripts\python.exe auto_upload_scans.py
) else if exist ".venv\Scripts\python.exe" (
    .venv\Scripts\python.exe auto_upload_scans.py
) else (
    python auto_upload_scans.py
)

echo.
pause
