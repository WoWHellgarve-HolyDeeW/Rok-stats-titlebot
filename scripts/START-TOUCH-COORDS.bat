@echo off
chcp 65001 >nul
title LDPlayer Touch Coordinates
cd /d "%~dp0RESEARCH\frida"
echo.
echo  Toca no emulador para ver as coordenadas X,Y.
echo  Ctrl+C para parar.
echo.
"C:\Users\nelso\AppData\Local\Programs\Python\Python312\python.exe" touch_coords.py %*
pause
