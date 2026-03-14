$scriptPath = Split-Path -Parent $MyInvocation.MyCommand.Path
Write-Host "Scripts directory set to: $scriptPath"
Set-Location $scriptPath

Write-Host "Installing virtual python enviroment..."
python.exe -m venv .venv
Write-Host "venv installed!"

Write-Host "Activating the virtual enviroment"
.\.venv\Scripts\Activate.ps1

Write-Host "Installing all packages from requirements.txt..."
pip.exe install -r requirements.txt
Write-Host "All remote packages installed!"

Write-Host "Installing local modules"
Write-Host "Scripts directory set to: $scriptPath\src"
cd src
pip.exe install -e .
Write-Host "All local modules installed!"

Write-Host "All ready to go!"
Write-Host "Press enter to exit the setup script!"
Read-Host
