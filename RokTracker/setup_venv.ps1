Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# Run from RokTracker folder
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptDir

if (-not (Test-Path .\venv)) {
  Write-Host "Creating venv at $scriptDir\venv" -ForegroundColor Cyan
  py -m venv venv
}

Write-Host "Activating venv" -ForegroundColor Cyan
. .\venv\Scripts\Activate.ps1

Write-Host "Upgrading pip tooling" -ForegroundColor Cyan
python -m pip install --upgrade pip wheel setuptools

Write-Host "Installing requirements_win64.txt" -ForegroundColor Cyan
pip install -r .\requirements_win64.txt

Write-Host "Done. To run Title Bot: .\start_title_bot.ps1" -ForegroundColor Green
