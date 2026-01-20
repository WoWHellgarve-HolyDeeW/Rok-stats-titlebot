Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptDir

if (-not (Test-Path .\venv\Scripts\Activate.ps1)) {
  Write-Host "venv not found. Run .\setup_venv.ps1 first." -ForegroundColor Yellow
  exit 1
}

. .\venv\Scripts\Activate.ps1
python .\title_bot.py
