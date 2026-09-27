# Build the Alert Mesh desktop app for Windows.
#
#   powershell -ExecutionPolicy Bypass -File packaging\build_windows.ps1      (from python-prototype\)
#
# Makes "dist\Alert Mesh\Alert Mesh.exe" (keep it inside its folder: the folder holds
# the parts it needs) and dist\Alert-Mesh-windows.zip (that folder, zipped for sharing).
# The first run makes a separate build environment, packaging\.venv-windows, with the
# newest Python 3 the Python launcher knows (py -3), or the python.exe named by
# $env:PYTHON. Needs Python 3.10 or newer from python.org, and the ..\alert-mesh folder
# next to this one. Later runs reuse the environment. Downloads the build tools from
# PyPI on the first run.
#
# NOT YET RUN: written on a Mac, where it cannot be tested (PROGRESS.md step 12.4).
# If installing pywebview fails on the newest Python (its Windows part, pythonnet, can
# lag behind new Python versions), set PYTHON to a Python 3.13 python.exe and try again.
# The window needs Microsoft Edge WebView2, which Windows 10 and 11 normally include.
#
# This is free and unencumbered software released into the public domain.
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

$Venv = "packaging\.venv-windows"
$VenvPython = "$Venv\Scripts\python.exe"
if ($env:PYTHON) { $Python = $env:PYTHON; $PythonArgs = @() } else { $Python = "py"; $PythonArgs = @("-3") }

if (-not (Test-Path "..\alert-mesh")) {
    throw "The Swift app folder (..\alert-mesh) is missing: the build copies the town list and the icon from it."
}

if (-not (Test-Path $VenvPython)) {
    & $Python @PythonArgs -c "import sys; sys.exit(sys.version_info < (3, 10))"
    if ($LASTEXITCODE -ne 0) {
        throw "Needs Python 3.10 or newer. Install it from https://www.python.org/downloads/ or set PYTHON to its python.exe."
    }
    Write-Host "Making the build environment ($Venv)"
    & $Python @PythonArgs -m venv $Venv
    if ($LASTEXITCODE -ne 0) { throw "Could not make the build environment." }
}
& $VenvPython -m pip install --quiet --upgrade pip
& $VenvPython -m pip install --quiet -r packaging\requirements-build.txt
if ($LASTEXITCODE -ne 0) { throw "Installing the build tools failed." }

Write-Host "Building the app (a few minutes)"
& "$Venv\Scripts\pyinstaller.exe" --noconfirm --clean --log-level WARN `
    --distpath dist --workpath build\pyinstaller packaging\alert_mesh.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed." }

# A window app has no text output, so --check also writes its result to a file.
Write-Host "Checking the finished app has every part it needs"
$Result = Join-Path ([System.IO.Path]::GetTempPath()) "alert-mesh-check.txt"
Remove-Item $Result -ErrorAction SilentlyContinue
$Exe = (Resolve-Path "dist\Alert Mesh\Alert Mesh.exe").Path
$Check = Start-Process -FilePath $Exe -ArgumentList "--check" -Wait -PassThru
if (Test-Path $Result) { Get-Content $Result }
if ($Check.ExitCode -ne 0) { throw "The finished app is missing a part (see above)." }

Remove-Item dist\Alert-Mesh-windows.zip -ErrorAction SilentlyContinue
Compress-Archive -Path "dist\Alert Mesh" -DestinationPath dist\Alert-Mesh-windows.zip

Write-Host ""
Write-Host "Done: dist\Alert Mesh\Alert Mesh.exe and dist\Alert-Mesh-windows.zip"
