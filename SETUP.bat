@echo off
REM ============================================================
REM  RoK Stats Hub - one-click setup for new users
REM  by WoWHellgarve-HolyDeeW
REM  https://github.com/WoWHellgarve-HolyDeeW/Rok-stats-titlebot
REM ============================================================
setlocal EnableDelayedExpansion
title RoK Stats Hub - Setup
color 0B
pushd "%~dp0"

echo.
echo   RoK Stats Hub - first-time setup
echo   by WoWHellgarve-HolyDeeW
echo   ------------------------------------------
echo.

REM --- Check Docker ---
where docker >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Docker is not installed or not on PATH.
    echo        Install Docker Desktop from https://www.docker.com/products/docker-desktop/
    echo        Then run SETUP.bat again.
    echo.
    pause
    exit /b 1
)
echo [OK] Docker found.

docker compose version >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Docker Compose v2 not available. Please update Docker Desktop.
    pause
    exit /b 1
)
echo [OK] Docker Compose v2 found.

REM --- Create .env from example if missing ---
if not exist ".env" (
    if exist ".env.example" (
        echo [..] Creating .env from .env.example
        copy /y ".env.example" ".env" >nul
        echo.
        echo   A new .env has been created. Open it and set at least:
        echo     AUTH_SECRET_KEY      (long random string^)
        echo     INTERNAL_API_KEY     (long random string^)
        echo     BOOTSTRAP_ADMIN_USERNAME + BOOTSTRAP_ADMIN_PASSWORD for the first admin
        echo.
        echo   You can also just continue with the defaults for local testing.
        echo.
        pause
    ) else (
        echo [WARN] .env.example not found. Continuing with whatever defaults docker-compose provides.
    )
) else (
    echo [OK] .env already exists.
)

REM --- Start the stack ---
echo.
echo [..] Building and starting containers. First run will download images and build, which can take a few minutes.
echo.
docker compose up -d --build
if errorlevel 1 (
    echo [ERROR] docker compose up failed. See the output above.
    pause
    exit /b 1
)

echo.
echo   ============================================
echo    RoK Stats Hub is starting.
echo.
echo    Frontend:   http://localhost:3000
echo    Backend:    http://localhost:8000
echo    API docs:   http://localhost:8000/docs
echo.
echo    To stop:    docker compose down
echo    To view logs: docker compose logs -f backend
echo   ============================================
echo.
echo   by WoWHellgarve-HolyDeeW
echo   https://github.com/WoWHellgarve-HolyDeeW/Rok-stats-titlebot
echo.
pause
popd
endlocal
