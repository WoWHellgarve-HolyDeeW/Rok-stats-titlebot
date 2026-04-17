@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion
title RoK Stats Hub
color 0B

set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"
set "BACKEND=%ROOT%\backend"
set "BOT_RUNTIME=%ROOT%\RokTracker\venv\Scripts\python.exe"
set "FRONTEND=%ROOT%\frontend-next"
set "PY=%BACKEND%\.venv\Scripts\python.exe"
if not exist "%BOT_RUNTIME%" set "BOT_RUNTIME=%PY%"
set "KINGDOM=0000"
set "DEVICE="
set "GAME_PKG=com.lilithgame.roc.gp"

REM ═══ Auto-detect ADB ═══
set "ADB="
if exist "C:\LDPlayer\LDPlayer9\adb.exe" set "ADB=C:\LDPlayer\LDPlayer9\adb.exe"
if not defined ADB if exist "%ROOT%\RokTracker\deps\platform-tools\adb.exe" set "ADB=%ROOT%\RokTracker\deps\platform-tools\adb.exe"
if not defined ADB if exist "C:\Program Files\BlueStacks_nxt\HD-Adb.exe" set "ADB=C:\Program Files\BlueStacks_nxt\HD-Adb.exe"
if not defined ADB if exist "%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe" set "ADB=%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe"

echo.
echo  ╔═══════════════════════════════════════════════╗
echo  ║           RoK Stats Hub — Launcher            ║
echo  ║  Backend + Frontend + Queue Bot + Ingame Chat ║
echo  ╚═══════════════════════════════════════════════╝
echo.

REM ═══ Pre-requisite checks ═══
if not exist "%PY%" (
    set "SETUP_PY="
    where py >nul 2>&1 && set "SETUP_PY=py"
    if not defined SETUP_PY (
        where python >nul 2>&1 && set "SETUP_PY=python"
    )
    if not defined SETUP_PY (
        echo  [X] Python nao encontrado! Instala Python 3.11+
        pause
        exit /b 1
    )
    echo  [SETUP] A criar backend venv...
    !SETUP_PY! -m venv "%BACKEND%\.venv"
    "%PY%" -m pip install --upgrade pip >nul
    "%PY%" -m pip install -r "%BACKEND%\requirements.txt"
    echo  [SETUP] Backend venv pronto.
)
where npm >nul 2>&1
if errorlevel 1 (
    echo  [X] Node.js/npm nao encontrado! Instala de https://nodejs.org
    pause
    exit /b 1
)
echo  [OK] Python e Node.js OK

REM ═══ Check/Install frontend deps ═══
if not exist "%FRONTEND%\node_modules" (
    echo  [SETUP] A instalar dependencias do frontend...
    pushd "%FRONTEND%"
    call npm install
    popd
)

call :is_http_ready http://127.0.0.1:8000/health
if errorlevel 1 (
    echo  [1/5] A iniciar Backend ^(FastAPI :8000^)...
    start "rok-backend" /min cmd /k "title RoK Backend && cd /d %BACKEND% && call .venv\Scripts\activate.bat && uvicorn app.main:app --host 0.0.0.0 --port 8000"
    set "STARTED_BACKEND=1"
    set "STARTED_ANY=1"
    call :wait_for_http http://127.0.0.1:8000/health 20
    if errorlevel 1 (
        echo  [!] Backend nao respondeu ao health check em :8000 a tempo.
    ) else (
        echo  [OK] Backend respondeu em :8000
    )
) else (
    echo  [1/5] Backend ja esta activo em :8000 - a reutilizar.
)

call :is_http_ready http://127.0.0.1:3000/
if errorlevel 1 (
    echo  [2/5] A iniciar Frontend ^(Next.js :3000^)...
    start "rok-frontend" /min cmd /k "title RoK Frontend && cd /d %FRONTEND% && set NEXT_PUBLIC_API_URL=http://localhost:8000 && npm run dev"
    set "STARTED_FRONTEND=1"
    set "STARTED_ANY=1"
    call :wait_for_http http://127.0.0.1:3000/ 30
    if errorlevel 1 (
        echo  [!] Frontend nao respondeu em :3000 a tempo.
    ) else (
        echo  [OK] Frontend respondeu em :3000
    )
) else (
    echo  [2/5] Frontend ja esta activo em :3000 - a reutilizar.
)

REM ═══ Frida Daemon — title bot + chat ═══
set "DAEMON_READY="
if defined ADB (
    call :detect_first_device
    if defined DEVICE set "DAEMON_READY=1"
)

if not defined DAEMON_READY (
    if not defined ADB (
        echo  [3/5] ADB nao encontrado — title bot indisponivel.
        goto :show_status
    )
    echo.
    echo  [3/5] Emulador nao detectado. A aguardar LDPlayer...
    echo        ^(Abre o LDPlayer se ainda nao esta aberto^)
    echo.
    set "WAIT_COUNT=0"
    :wait_emulator
    set /a WAIT_COUNT+=1
    if !WAIT_COUNT! gtr 60 (
        echo  [!] Timeout — emulador nao apareceu em 2 minutos.
        echo      Podes correr START-FRIDA.bat depois.
        goto :show_status
    )
    timeout /t 2 /nobreak >nul
    call :detect_first_device
    if not defined DEVICE (
        <nul set /p "=  A aguardar emulador... [!WAIT_COUNT!/60]   "
        echo.
        goto :wait_emulator
    )
    set "DAEMON_READY=1"
    echo  [OK] Emulador detectado: !DEVICE!
)

REM ═══ Frida-server + port forward ═══
echo  [3/5] A preparar Frida...
set "ROK_ADB_PATH=%ADB%"
set "ROK_DEVICE_SERIAL=!DEVICE!"
set "CHAT_RELAY_ALLOW_SPAWN=1"
"%ADB%" -s "!DEVICE!" shell "su -c 'pidof frida-server-16 >/dev/null || (killall frida-server-16 2>/dev/null; sleep 1; nohup /data/local/tmp/frida-server-16 --disable-preload --listen 0.0.0.0:27042 > /dev/null 2>&1 &)'" 2>nul
timeout /t 3 /nobreak >nul
"%ADB%" -s "!DEVICE!" forward tcp:27142 tcp:27042 >nul 2>&1
call :launch_game_if_needed

set "TITLE_BOT_PID="
call :find_process_by_match "_frida_daemon.py --kingdom %KINGDOM% --mode title_bot" TITLE_BOT_PID
if errorlevel 1 (
    echo  [4/5] A iniciar Queue Bot ^(kingdom %KINGDOM%^)...
    start "rok-frida" cmd /k "title RoK Title Bot && cd /d %ROOT% && %BOT_RUNTIME% -u _frida_daemon.py --kingdom %KINGDOM% --mode title_bot"
    set "STARTED_TITLE_BOT=1"
    set "STARTED_ANY=1"
) else (
    echo  [4/5] Queue Bot ja esta a correr ^(pid=!TITLE_BOT_PID!^) - a reutilizar.
)

set "CHAT_RELAY_PID="
call :find_process_by_match "_chat_relay.py --kingdom %KINGDOM%" CHAT_RELAY_PID
if errorlevel 1 (
    echo  [5/5] A iniciar Chat Relay ingame ^(kingdom %KINGDOM%^)...
    start "rok-chat-relay" cmd /k "title RoK Chat Relay && cd /d %ROOT% && %BOT_RUNTIME% -u _chat_relay.py --kingdom %KINGDOM% --api http://127.0.0.1:8000"
    set "STARTED_CHAT_RELAY=1"
    set "STARTED_ANY=1"
) else (
    echo  [5/5] Chat Relay ja esta a correr ^(pid=!CHAT_RELAY_PID!^) - a reutilizar.
)

:show_status
echo.
echo  ════════════════════════════════════════════════
echo    TUDO INICIADO!
echo  ════════════════════════════════════════════════
echo.
echo    Backend:    http://localhost:8000
echo    Frontend:   http://localhost:3000
echo    Title Bot:  http://localhost:3000/0000/scanner?tab=titles
echo    API Docs:   http://localhost:8000/docs
if defined DAEMON_READY (
echo    Frida:      Queue bot activo + relay de chat ingame
)
echo.
if defined STARTED_ANY (
echo    Carrega qualquer tecla para PARAR os servicos iniciados por esta janela.
) else (
echo    Nenhum servico novo foi iniciado; os existentes vao continuar activos.
echo    Carrega qualquer tecla para sair sem matar os processos existentes.
)
echo  ════════════════════════════════════════════════
pause >nul

if defined STARTED_BACKEND taskkill /FI "WindowTitle eq RoK Backend*" /F >nul 2>&1
if defined STARTED_FRONTEND taskkill /FI "WindowTitle eq RoK Frontend*" /F >nul 2>&1
if defined STARTED_TITLE_BOT taskkill /FI "WindowTitle eq RoK Title Bot*" /F >nul 2>&1
if defined STARTED_CHAT_RELAY taskkill /FI "WindowTitle eq RoK Chat Relay*" /F >nul 2>&1
if defined STARTED_ANY (
    echo  Servicos iniciados por esta janela foram parados.
) else (
    echo  Nada para parar.
)
endlocal
goto :eof

:is_port_listening
netstat -ano | findstr /R /C:":%~1 .*LISTENING" >nul 2>&1
exit /b %errorlevel%

:wait_for_port
set "WAIT_PORT=%~1"
set /a WAIT_ATTEMPTS=%~2
:wait_for_port_loop
call :is_port_listening %WAIT_PORT%
if not errorlevel 1 exit /b 0
set /a WAIT_ATTEMPTS-=1
if !WAIT_ATTEMPTS! LEQ 0 exit /b 1
timeout /t 1 /nobreak >nul
goto :wait_for_port_loop

:is_http_ready
powershell -NoProfile -Command "try { $r = Invoke-WebRequest -UseBasicParsing '%~1' -TimeoutSec 3; if ($r.StatusCode -ge 200 -and $r.StatusCode -lt 500) { exit 0 } else { exit 1 } } catch { exit 1 }" >nul 2>&1
exit /b %errorlevel%

:wait_for_http
set "WAIT_URL=%~1"
set /a WAIT_HTTP_ATTEMPTS=%~2
:wait_for_http_loop
call :is_http_ready %WAIT_URL%
if not errorlevel 1 exit /b 0
set /a WAIT_HTTP_ATTEMPTS-=1
if !WAIT_HTTP_ATTEMPTS! LEQ 0 exit /b 1
timeout /t 1 /nobreak >nul
goto :wait_for_http_loop

:detect_first_device
set "DEVICE="
for /f "skip=1 tokens=1,2" %%a in ('"%ADB%" devices 2^>nul') do (
    if /I "%%b"=="device" if not defined DEVICE set "DEVICE=%%a"
)
if defined DEVICE exit /b 0
exit /b 1

:is_game_running
for /f "usebackq delims=" %%P in (`"%ADB%" -s "!DEVICE!" shell "pidof %GAME_PKG%" 2^>nul`) do (
    if not "%%P"=="" exit /b 0
)
exit /b 1

:launch_game_if_needed
call :is_game_running
if not errorlevel 1 (
    echo  [OK] Jogo ja esta aberto no emulador.
    exit /b 0
)
echo  [3.5/5] A abrir Rise of Kingdoms via ADB...
"%ADB%" -s "!DEVICE!" shell "monkey -p %GAME_PKG% -c android.intent.category.LAUNCHER 1" >nul 2>&1
timeout /t 5 /nobreak >nul
call :is_game_running
if not errorlevel 1 (
    echo  [OK] Jogo iniciado. O relay vai anexar quando chegar ao mapa.
    exit /b 0
)
echo  [!] O launcher tentou abrir o jogo, mas o processo ainda nao apareceu.
echo      Se o emulador estiver lento, abre o jogo manualmente e deixa-o no mapa.
exit /b 0

:find_process_by_match
set "%~2="
set "LAUNCHER_MATCH=%~1"
for /f "usebackq delims=" %%P in (`powershell -NoProfile -Command "$pattern = $env:LAUNCHER_MATCH; $proc = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -and $_.CommandLine -like ('*' + $pattern + '*') } | Select-Object -First 1 -ExpandProperty ProcessId; if ($proc) { Write-Output $proc; exit 0 } else { exit 1 }"`) do set "%~2=%%P"
if defined %~2 exit /b 0
exit /b 1
