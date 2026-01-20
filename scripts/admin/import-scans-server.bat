@echo off
setlocal
title RoK Stats - Import Scans (Server)
chcp 65001 >nul

echo ============================================
echo   RoK Stats - Import Scans do Servidor
echo ============================================
echo.
echo Este script importa os CSVs que estao no servidor
echo sem necessitar de token admin (acesso local).
echo.

REM Usar curl para chamar o endpoint interno
curl -X POST "http://localhost:8000/internal/import-scans" -H "Content-Type: application/json"

echo.
echo.
pause
