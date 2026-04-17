@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion
title RoK Frida — Setup
color 0E

set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"

echo.
echo  ╔═══════════════════════════════════════════════════════╗
echo  ║            RoK Frida Monitor — Setup                  ║
echo  ║  Verifica e configura tudo para qualquer maquina      ║
echo  ╚═══════════════════════════════════════════════════════╝
echo.

set "ERRORS=0"

REM ═══ 1) Python ═══
echo  [1/5] A verificar Python...
set "PY="
if exist "%ROOT%\backend\.venv\Scripts\python.exe" (
    set "PY=%ROOT%\backend\.venv\Scripts\python.exe"
    echo        Encontrado: venv do backend
)
if not defined PY (
    py -3.12 --version >nul 2>&1 && set "PY=py -3.12"
)
if not defined PY (
    py -3 --version >nul 2>&1 && set "PY=py -3"
)
if not defined PY (
    python --version >nul 2>&1 && set "PY=python"
)
if not defined PY (
    echo        [ERRO] Python nao encontrado!
    echo        Instala em: https://www.python.org/downloads/
    set /a ERRORS+=1
) else (
    for /f "tokens=*" %%v in ('%PY% --version 2^>^&1') do echo        [OK] %%v
)

REM ═══ 2) Frida module ═══
echo  [2/5] A verificar modulo frida...
if defined PY (
    %PY% -c "import frida; print('        [OK] frida', frida.__version__)" 2>nul
    if errorlevel 1 (
        echo        [WARN] Modulo frida nao instalado. A instalar...
        %PY% -m pip install frida frida-tools
        %PY% -c "import frida; print('        [OK] frida', frida.__version__)" 2>nul
        if errorlevel 1 (
            echo        [ERRO] Falhou a instalar frida.
            set /a ERRORS+=1
        )
    )
) else (
    echo        [SKIP] Precisa de Python primeiro
)

REM ═══ 3) ADB ═══
echo  [3/5] A verificar ADB...
set "ADB="
if exist "%ROOT%\RokTracker\deps\platform-tools\adb.exe" set "ADB=%ROOT%\RokTracker\deps\platform-tools\adb.exe"
if not defined ADB if exist "C:\LDPlayer\LDPlayer9\adb.exe" set "ADB=C:\LDPlayer\LDPlayer9\adb.exe"
if not defined ADB if exist "C:\LDPlayer\LDPlayer4\adb.exe" set "ADB=C:\LDPlayer\LDPlayer4\adb.exe"
if not defined ADB if exist "C:\Program Files\BlueStacks_nxt\HD-Adb.exe" set "ADB=C:\Program Files\BlueStacks_nxt\HD-Adb.exe"
if not defined ADB if exist "C:\Program Files (x86)\Nox\bin\adb.exe" set "ADB=C:\Program Files (x86)\Nox\bin\adb.exe"
if not defined ADB if exist "%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe" set "ADB=%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe"
if not defined ADB (
    where adb.exe >nul 2>&1 && set "ADB=adb.exe"
)
if not defined ADB (
    echo        [ERRO] ADB nao encontrado.
    echo        Instala LDPlayer, BlueStacks ou Android SDK.
    set /a ERRORS+=1
) else (
    echo        [OK] ADB: %ADB%
)

REM ═══ 4) Emulador ligado ═══
echo  [4/5] A verificar emulador...
if defined ADB (
    set "DEVICE="
    for /f "tokens=1" %%d in ('"%ADB%" devices 2^>nul ^| findstr /R "device$"') do (
        if not defined DEVICE set "DEVICE=%%d"
    )
    if defined DEVICE (
        echo        [OK] Emulador: !DEVICE!
    ) else (
        echo        [WARN] Nenhum emulador ligado. Inicia o LDPlayer primeiro.
    )
) else (
    echo        [SKIP] Precisa de ADB primeiro
)

REM ═══ 5) Frida-server no emulador ═══
echo  [5/5] A verificar frida-server no emulador...
if defined ADB if defined DEVICE (
    set "FS_EXISTS="
    for /f %%x in ('"%ADB%" -s !DEVICE! shell "ls /data/local/tmp/frida-server-16 2>/dev/null"') do (
        set "FS_EXISTS=1"
    )
    if defined FS_EXISTS (
        echo        [OK] frida-server-16 presente no emulador
        REM Check if running
        set "FS_RUNNING="
        for /f %%p in ('"%ADB%" -s !DEVICE! shell "pidof frida-server-16" 2^>nul') do (
            set "FS_RUNNING=1"
        )
        if defined FS_RUNNING (
            echo        [OK] frida-server activo
        ) else (
            echo        [INFO] frida-server nao esta a correr (START-FRIDA.bat vai inicia-lo)
        )
    ) else (
        echo        [ERRO] frida-server-16 NAO encontrado em /data/local/tmp/
        echo        Precisas de fazer push do binario para o emulador:
        echo          adb push frida-server-16.5.2-android-x86_64 /data/local/tmp/frida-server-16
        echo          adb shell "su -c 'chmod 755 /data/local/tmp/frida-server-16'"
        set /a ERRORS+=1
    )
) else (
    echo        [SKIP] Precisa de emulador ligado
)

echo.
echo  ─────────────────────────────────────────────────────────
if %ERRORS% GTR 0 (
    echo  [!] %ERRORS% problema(s) encontrado(s). Corrige antes de usar START-FRIDA.bat
) else (
    echo  [OK] Tudo pronto! Usa START-FRIDA.bat para iniciar o monitor.
)
echo  ─────────────────────────────────────────────────────────
echo.
pause
endlocal
