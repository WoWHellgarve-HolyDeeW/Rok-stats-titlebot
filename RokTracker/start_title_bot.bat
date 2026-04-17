@echo off
setlocal
cd /d %~dp0

if not exist venv\Scripts\activate.bat (
  echo venv not found. Run setup_venv.ps1 first.
  pause
  exit /b 1
)

call venv\Scripts\activate.bat
python title_bot.py
pause
