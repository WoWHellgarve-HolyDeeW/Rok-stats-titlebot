@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion
title RoK Frida Daemon
color 0A

set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"
set "KINGDOM=0000"
set "GAME_PKG=com.lilithgame.roc.gp"
set "PY=%ROOT%\RokTracker\venv\Scripts\python.exe"

REM ═══ Auto-detect ADB (checks multiple locations + PATH) ═══
set "ADB="
REM Check project deps first
if exist "%ROOT%\RokTracker\deps\platform-tools\adb.exe" set "ADB=%ROOT%\RokTracker\deps\platform-tools\adb.exe"
REM Check common emulators
if not defined ADB if exist "C:\LDPlayer\LDPlayer9\adb.exe" set "ADB=C:\LDPlayer\LDPlayer9\adb.exe"
if not defined ADB if exist "C:\LDPlayer\LDPlayer4\adb.exe" set "ADB=C:\LDPlayer\LDPlayer4\adb.exe"
if not defined ADB if exist "C:\Program Files\BlueStacks_nxt\HD-Adb.exe" set "ADB=C:\Program Files\BlueStacks_nxt\HD-Adb.exe"
if not defined ADB if exist "C:\Program Files (x86)\Nox\bin\adb.exe" set "ADB=C:\Program Files (x86)\Nox\bin\adb.exe"
if not defined ADB if exist "%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe" set "ADB=%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe"
REM Check PATH
if not defined ADB (
    where adb.exe >nul 2>&1 && set "ADB=adb.exe"
)

echo.
echo  ╔═══════════════════════════════════════════════════════╗
echo  ║       RoK Frida Daemon — Queue Bot + Relay          ║
echo  ║   Titles pela queue, pedidos automáticos via chat   ║
echo  ╚═══════════════════════════════════════════════════════╝
echo.

REM ═══ Check ADB ═══
if not defined ADB (
    echo  [ERRO] ADB nao encontrado.
    echo         Instala LDPlayer, BlueStacks, Nox ou Android SDK.
    echo         Ou adiciona adb.exe ao PATH.
    pause
    exit /b 1
)
echo  [OK] ADB: %ADB%

REM ═══ Check emulator connected ═══
"%ADB%" devices 2>nul | findstr /R "device$" >nul 2>&1
if errorlevel 1 (
    echo  [ERRO] Nenhum emulador ligado. Inicia o LDPlayer primeiro.
    pause
    exit /b 1
)
REM Auto-detect first connected device
set "DEVICE="
for /f "skip=1 tokens=1,2" %%a in ('"%ADB%" devices 2^>nul') do (
    if /I "%%b"=="device" if not defined DEVICE set "DEVICE=%%a"
)
if not defined DEVICE (
    echo  [ERRO] ADB respondeu, mas nao foi possivel identificar o emulador.
    pause
    exit /b 1
)
echo  [OK] Emulador: %DEVICE%
set "ROK_ADB_PATH=%ADB%"
set "ROK_DEVICE_SERIAL=%DEVICE%"
set "CHAT_RELAY_ALLOW_SPAWN=1"

REM ═══ Auto-detect Python ═══
REM Prefer the RokTracker venv because it already includes frida + screen-verify deps.
if not exist "%PY%" set "PY=%ROOT%\backend\.venv\Scripts\python.exe"
if not exist "%PY%" set "PY="
REM Check py launcher (preferred on Windows)
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
    echo  [ERRO] Python nao encontrado. Instala Python 3.10+.
    pause
    exit /b 1
)
echo  [OK] Python: %PY%

REM ═══ Check frida module ═══
%PY% -c "import frida" >nul 2>&1
if errorlevel 1 (
    echo  [WARN] Modulo frida nao encontrado. A instalar...
    %PY% -m pip install frida frida-tools
)

REM ═══ Ensure frida-server is running ═══
set "FRIDA_RUNNING="
for /f %%f in ('"%ADB%" -s %DEVICE% shell "pidof frida-server-16" 2^>nul') do (
    set "FRIDA_RUNNING=1"
)
if not defined FRIDA_RUNNING (
    echo  [INFO] frida-server nao esta a correr. A iniciar...
    "%ADB%" -s %DEVICE% shell "su -c 'killall frida-server-16 2>/dev/null; sleep 1; nohup /data/local/tmp/frida-server-16 --disable-preload --listen 0.0.0.0:27042 > /dev/null 2>&1 &'" 2>nul
    timeout /t 4 /nobreak >nul
    for /f %%f in ('"%ADB%" -s %DEVICE% shell "pidof frida-server-16" 2^>nul') do (
        set "FRIDA_RUNNING=1"
    )
    if not defined FRIDA_RUNNING (
        echo  [ERRO] Nao foi possivel iniciar frida-server.
        echo         Verifica se /data/local/tmp/frida-server-16 existe no emulador.
        pause
        exit /b 1
    )
)
echo  [OK] frida-server activo

REM ═══ Port forward ═══
"%ADB%" -s %DEVICE% forward tcp:27142 tcp:27042 >nul 2>&1
call :launch_game_if_needed

call :is_port_listening 8000
if errorlevel 1 (
    echo  [WARN] Backend nao esta a escutar em :8000.
    echo         O bot e o relay vao arrancar, mas a queue/chat so sincronizam quando a API subir.
) else (
    echo  [OK] Backend detectado em :8000
)

echo.
echo  ─────────────────────────────────────────────────────────
echo   A iniciar Chat Relay separado e Queue Bot principal
echo   Pressiona Ctrl+C para parar.
echo  ─────────────────────────────────────────────────────────
echo.

cd /d "%ROOT%"
set "CHAT_RELAY_PID="
call :find_process_by_match "_chat_relay.py --kingdom %KINGDOM%" CHAT_RELAY_PID
if errorlevel 1 (
    start "rok-chat-relay" cmd /k "title RoK Chat Relay && cd /d %ROOT% && %PY% -u _chat_relay.py --kingdom %KINGDOM% --api http://127.0.0.1:8000"
    set "STARTED_CHAT_RELAY=1"
) else (
    echo  [INFO] Chat Relay ja esta a correr ^(pid=!CHAT_RELAY_PID!^) - a reutilizar.
)

set "TITLE_BOT_PID="
call :find_process_by_match "_frida_daemon.py --kingdom %KINGDOM% --mode title_bot" TITLE_BOT_PID
if errorlevel 1 (
    %PY% -u _frida_daemon.py --kingdom %KINGDOM% --mode title_bot
) else (
    echo  [INFO] Queue Bot ja esta a correr ^(pid=!TITLE_BOT_PID!^) - nao vou arrancar outro.
    set "SKIPPED_DAEMON_START=1"
)

echo.
if defined STARTED_CHAT_RELAY taskkill /FI "WindowTitle eq RoK Chat Relay*" /F >nul 2>&1
if defined SKIPPED_DAEMON_START (
    echo  Nenhum novo Queue Bot foi iniciado.
) else (
    echo  Daemon parado.
)
pause
endlocal
goto :eof

:is_port_listening
netstat -ano | findstr /R /C:":%~1 .*LISTENING" >nul 2>&1
exit /b %errorlevel%

:is_game_running
for /f "usebackq delims=" %%P in (`"%ADB%" -s %DEVICE% shell "pidof %GAME_PKG%" 2^>nul`) do (
    if not "%%P"=="" exit /b 0
)
exit /b 1

:launch_game_if_needed
call :is_game_running
if not errorlevel 1 (
    echo  [OK] Jogo ja esta aberto no emulador.
    exit /b 0
)
echo  [INFO] A abrir Rise of Kingdoms via ADB...
"%ADB%" -s %DEVICE% shell "monkey -p %GAME_PKG% -c android.intent.category.LAUNCHER 1" >nul 2>&1
timeout /t 5 /nobreak >nul
call :is_game_running
if not errorlevel 1 (
    echo  [OK] Jogo iniciado. O relay vai anexar quando chegar ao mapa.
    exit /b 0
)
echo  [WARN] O launcher tentou abrir o jogo, mas o processo ainda nao apareceu.
echo         Se o emulador estiver lento, abre o jogo manualmente e deixa-o no mapa.
exit /b 0

:find_process_by_match
set "%~2="
set "LAUNCHER_MATCH=%~1"
for /f "usebackq delims=" %%P in (`powershell -NoProfile -Command "$pattern = $env:LAUNCHER_MATCH; $proc = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -and $_.CommandLine -like ('*' + $pattern + '*') } | Select-Object -First 1 -ExpandProperty ProcessId; if ($proc) { Write-Output $proc; exit 0 } else { exit 1 }"`) do set "%~2=%%P"
if defined %~2 exit /b 0
exit /b 1
