$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
if ($env:OS -ne "Windows_NT") { throw "Build the Windows executable on Windows." }
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    # Respect setup-python/PATH selection so each CI matrix entry tests its runtime.
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw "Creating the Python environment failed." }
}
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt pyinstaller==6.16.0
if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed." }
& .\.venv\Scripts\python.exe -m unittest discover -s tests -v
if ($LASTEXITCODE -ne 0) { throw "Tests failed." }
$buildWorkspace = Join-Path $PSScriptRoot ("build\release-" + [guid]::NewGuid().ToString("N"))
& .\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --onefile --windowed --workpath $buildWorkspace --add-data "dashboard;dashboard" --collect-all tzdata --name UsageTray usage_tray.py
if ($LASTEXITCODE -ne 0) { throw "Packaging failed." }
& .\.venv\Scripts\python.exe tools/release_smoke.py --exe dist/UsageTray.exe
if ($LASTEXITCODE -ne 0) { throw "Packaged release smoke checks failed." }
Write-Host "Built and smoke-tested $PSScriptRoot\dist\UsageTray.exe"
