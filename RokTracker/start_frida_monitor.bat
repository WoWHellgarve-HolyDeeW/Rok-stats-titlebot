@echo off
REM Start the Frida monitor for real-time game data capture
REM This hooks into Rise of Kingdoms via Lua VM to capture:
REM   - Chat messages (KD/LK/LK_CROSS)
REM   - Player data (VIP, power, kills, acclaims)
REM   - Coordinates
REM   - Title requests (auto-posted to backend queue)
REM
REM Prerequisites:
REM   - frida-server running on emulator (adb shell)
REM   - Game running with known PID
REM   - Backend API running (optional, for title queue)

set GAME_PID=23400
set BACKEND_URL=http://localhost:8000
set API_TOKEN=change-me-internal-api-key
set KINGDOM=0000

echo ============================================
echo  RoK Frida Monitor — Starting...
echo  Game PID: %GAME_PID%
echo  Backend: %BACKEND_URL%
echo  Kingdom: %KINGDOM%
echo ============================================

cd /d "%~dp0frida"
python -u rok_monitor.py --pid %GAME_PID% --backend %BACKEND_URL% --token %API_TOKEN% --kingdom %KINGDOM% --duration 0
pause
