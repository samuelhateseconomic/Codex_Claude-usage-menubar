$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
if ($env:OS -ne "Windows_NT") { throw "Build the Windows executable on Windows." }
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    py -3 -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw "Creating the Python environment failed." }
}
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt pyinstaller==6.16.0
if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed." }
& .\.venv\Scripts\python.exe -m unittest discover -s tests -v
if ($LASTEXITCODE -ne 0) { throw "Tests failed." }
& .\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --onefile --windowed --name UsageTray usage_tray.py
if ($LASTEXITCODE -ne 0) { throw "Packaging failed." }
Write-Host "Built $PSScriptRoot\dist\UsageTray.exe"
