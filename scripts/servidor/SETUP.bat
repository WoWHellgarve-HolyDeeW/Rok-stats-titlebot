@echo off
setlocal EnableDelayedExpansion
title RoK Stats - SETUP SERVIDOR
chcp 65001 >nul
echo ============================================
echo   RoK Stats Hub - SETUP COMPLETO SERVIDOR
echo ============================================
echo.

REM Detecta automaticamente o caminho do projeto
set "PROJECT=%~dp0..\.."
pushd "%PROJECT%"
set "PROJECT=%CD%"
popd

echo Pasta do projeto: %PROJECT%
echo.

echo [1/9] Verificando Python...
python --version
if errorlevel 1 (
    echo [ERRO] Python nao encontrado!
    pause
    exit /b 1
)
echo      OK!

echo.
echo [2/9] Verificando Node.js...
node --version
if errorlevel 1 (
    echo [ERRO] Node.js nao encontrado!
    pause
    exit /b 1
)
echo      OK!

echo.
echo [3/9] Verificando npm...
call npm --version
echo      OK!

echo.
echo [4/9] Configurando Firewall (portas 3000 e 8000)...
netsh advfirewall firewall delete rule name="RoK Stats Web (3000)" >nul 2>&1
netsh advfirewall firewall delete rule name="RoK Stats API (8000)" >nul 2>&1
netsh advfirewall firewall add rule name="RoK Stats Web (3000)" dir=in action=allow protocol=TCP localport=3000
netsh advfirewall firewall add rule name="RoK Stats API (8000)" dir=in action=allow protocol=TCP localport=8000
echo      Firewall OK!

echo.
echo [5/9] Preparando Backend...
cd /d "%PROJECT%\backend"
echo      Pasta: %CD%

if exist ".venv" (
    echo      Removendo venv antigo...
    rmdir /s /q .venv
)

echo      Criando novo venv...
python -m venv .venv

if not exist ".venv\Scripts\python.exe" (
    echo      [ERRO] venv nao foi criado!
    pause
    exit /b 1
)
echo      venv OK!

echo.
echo [6/9] Instalando dependencias Python...
call .venv\Scripts\activate.bat
echo      Atualizando pip...
python -m pip install --upgrade pip
echo      Instalando requirements.txt...
pip install -r requirements.txt
echo      Backend OK!

echo.
echo [7/9] Criando base de dados...
python -m alembic upgrade head
echo      Database OK!

echo.
echo [8/9] Instalando e buildando Frontend...
cd /d "%PROJECT%\frontend-next"
echo      Instalando npm packages...
call npm install
echo      Fazendo build de producao...
call npm run build
echo      Frontend OK!

echo.
echo [9/9] Instalando Git Hook para auto-upload...
cd /d "%PROJECT%"
if exist "hooks\post-merge" (
    copy /Y "hooks\post-merge" ".git\hooks\post-merge" >nul
    echo      Git Hook OK!
) else (
    echo      [SKIP] Hook nao encontrado
)

echo.
echo ============================================
echo          SETUP COMPLETO!
echo ============================================
echo.
echo Agora podes executar:
echo   scripts\servidor\START.bat
echo.
echo URLs (apos iniciar):
echo   Website: http://localhost:3000
echo   API:     http://localhost:8000
echo ============================================
echo.
pause
endlocal
