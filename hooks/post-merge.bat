@echo off
REM Git post-merge hook for Windows
REM Instalar: copy hooks\post-merge.bat .git\hooks\post-merge

echo === Post-merge hook: Checking for new scans ===

REM Check if any CSV files changed
git diff-tree -r --name-only --no-commit-id ORIG_HEAD HEAD | findstr /i "scans_kingdom.*\.csv" >nul
if %errorlevel% equ 0 (
    echo New scan files detected! Running auto-upload...
    cd RokTracker
    
    if exist "venv\Scripts\python.exe" (
        venv\Scripts\python.exe auto_upload_scans.py
    ) else if exist ".venv\Scripts\python.exe" (
        .venv\Scripts\python.exe auto_upload_scans.py
    ) else (
        python auto_upload_scans.py
    )
    
    cd ..
    echo Auto-upload complete!
) else (
    echo No new scan files.
)
