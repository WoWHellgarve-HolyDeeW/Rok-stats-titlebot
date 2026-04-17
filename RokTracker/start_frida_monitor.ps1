# Start the Frida monitor for real-time game data capture
# This hooks into Rise of Kingdoms via Lua VM to capture chat, players, coords, titles

param(
    [int]$GamePID = 23400,
    [string]$BackendURL = "http://localhost:8000",
    [string]$ApiToken = "change-me-internal-api-key",
    [int]$Kingdom = 0000,
    [int]$Duration = 0  # 0 = infinite
)

Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  RoK Frida Monitor" -ForegroundColor Cyan
Write-Host "  PID: $GamePID | Kingdom: $Kingdom" -ForegroundColor Cyan
Write-Host "  Backend: $BackendURL" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan

Push-Location "$PSScriptRoot\frida"
try {
    python -u rok_monitor.py `
        --pid $GamePID `
        --backend $BackendURL `
        --token $ApiToken `
        --kingdom $Kingdom `
        --duration $Duration
} finally {
    Pop-Location
}
