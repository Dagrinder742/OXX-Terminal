# Automatically set location to the script's directory
Set-Location $PSScriptRoot

Write-Host "[+] RUNNING MAINTENANCE..." -ForegroundColor Green
Write-Host "[+] RUNNING WINGET PACKAGE UPDATE..." -ForegroundColor Green
winget upgrade

Write-Host "[+] RUNNING MAINTENANCE..." -ForegroundColor Green
Write-Host "[+] RUNNING BANDIT YAML..." -ForegroundColor Green
bandit -c bandit.yaml -r . --severity-level all --confidence-level all --ignore-nosec

Write-Host "[+] RUNNING MAINTENANCE..." -ForegroundColor Green
Write-Host "[+] RUNNING PIP AUDIT..." -ForegroundColor Green
pip-audit
