$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$env:PYTHONPATH = Join-Path $Root "src"
$PreviousDataRoot = $env:PA2_DATA_ROOT
if (-not $env:PA2_DATA_ROOT) { $env:PA2_DATA_ROOT = Join-Path $Root 'runtime-data/build-tests' }
Push-Location $Root
try {
    & ".venv\Scripts\python.exe" -m pytest
    if ($LASTEXITCODE -ne 0) { throw 'Tests failed; packaging stopped.' }
    # Build in a staging directory: COLLECT may replace its output directory.
    # Never point it at the project root containing the sources and user data.
    $Distribution = Join-Path $Root 'build/distribution'
    & ".venv\Scripts\python.exe" -m PyInstaller --noconfirm --distpath $Distribution "packaging\pa2.spec"
    if ($LASTEXITCODE -ne 0) { throw 'Packaging failed.' }
    $Release = Join-Path $Distribution 'PA2'
    foreach ($Name in @('PA2.exe','_internal')) {
        if (-not (Test-Path -LiteralPath (Join-Path $Release $Name))) { throw "Missing packaged output: $Name" }
    }
    # Keep the previous runtime recoverable while putting the current EXE next
    # to README, source and launchers in PA2_ver1.
    $PreviousRelease = Join-Path $Root ('build/previous-release-' + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $PreviousRelease | Out-Null
    foreach ($Name in @('PA2.exe','_internal')) {
        $InstalledPath = Join-Path $Root $Name
        if (Test-Path -LiteralPath $InstalledPath) {
            Move-Item -LiteralPath $InstalledPath -Destination (Join-Path $PreviousRelease $Name)
        }
        Move-Item -LiteralPath (Join-Path $Release $Name) -Destination $InstalledPath
    }
    Write-Host "PA² 실행 파일: $(Join-Path $Root 'PA2.exe')"
} finally { $env:PA2_DATA_ROOT = $PreviousDataRoot; Pop-Location }

