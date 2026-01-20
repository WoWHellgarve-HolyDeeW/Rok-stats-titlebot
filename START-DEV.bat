@echo off
REM ============================================
REM   ROK STATS HUB - START DEVELOPMENT
REM ============================================
REM Starts both backend and frontend servers
REM ============================================

echo.
echo ============================================
echo   STARTING ROK STATS HUB
echo ============================================
echo.

REM Start Backend in new window
echo Starting Backend on http://localhost:8000 ...
start "RoK Stats - Backend" cmd /k "cd backend && .venv\Scripts\activate && uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload"

REM Wait a moment for backend to start
timeout /t 3 /nobreak >nul

REM Start Frontend in new window
echo Starting Frontend on http://localhost:3000 ...
start "RoK Stats - Frontend" cmd /k "cd frontend-next && npm run dev"

echo.
echo ============================================
echo   SERVERS STARTING...
echo ============================================
echo.
echo Backend API:  http://localhost:8000
echo Dashboard:    http://localhost:3000
echo API Docs:     http://localhost:8000/docs
echo.
echo Close the terminal windows to stop the servers.
echo.
pause
