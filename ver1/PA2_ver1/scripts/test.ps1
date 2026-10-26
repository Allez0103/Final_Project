$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$env:PYTHONPATH = Join-Path $Root "src"
$PreviousDataRoot = $env:PA2_DATA_ROOT
if (-not $env:PA2_DATA_ROOT) { $env:PA2_DATA_ROOT = Join-Path $Root 'runtime-data/test-suite' }
Push-Location $Root
try {
    & (Join-Path $Root ".venv\Scripts\python.exe") -m pytest
    if ($LASTEXITCODE -ne 0) { throw 'Tests failed.' }
} finally { $env:PA2_DATA_ROOT = $PreviousDataRoot; Pop-Location }

