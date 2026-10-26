param([string]$Python = "")
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Venv = Join-Path $Root ".venv"
$SetupTemp = Join-Path $Root ".setup-tmp"

if ($Python) {
    $PythonExe = $Python
    $PythonArgs = @()
} else {
    $PythonExe = $null
    $PythonArgs = @()
    $Candidates = @(
        @{ Exe = "py"; Args = @("-3.13") },
        @{ Exe = (Join-Path $env:LOCALAPPDATA "Programs\Python\Python313\python.exe"); Args = @() },
        @{ Exe = "python"; Args = @() }
    )
    foreach ($Candidate in $Candidates) {
        try {
            $Version = & $Candidate.Exe @($Candidate.Args) -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
            if ($LASTEXITCODE -eq 0 -and $Version -eq "3.13") {
                $PythonExe = $Candidate.Exe
                $PythonArgs = $Candidate.Args
                break
            }
        } catch {
            continue
        }
    }
    if (-not $PythonExe) {
        throw "Python 3.13 x64를 찾지 못했습니다. -Python 인수로 python.exe 경로를 지정하세요."
    }
}

if (-not (Test-Path -LiteralPath (Join-Path $Venv "Scripts\python.exe"))) {
    & $PythonExe @PythonArgs -m venv $Venv
}

New-Item -ItemType Directory -Force -Path $SetupTemp | Out-Null
$OldTemp = $env:TEMP
$OldTmp = $env:TMP
try {
    $env:TEMP = $SetupTemp
    $env:TMP = $SetupTemp
    $VenvPython = Join-Path $Venv "Scripts\python.exe"
    & $VenvPython -m ensurepip --upgrade
    & $VenvPython -m pip install --requirement (Join-Path $Root "requirements-lock.txt")
    & $VenvPython -m pip install --no-deps --no-build-isolation --editable $Root
    Write-Host "PA² 개발 환경 준비 완료: $Venv"
} finally {
    $env:TEMP = $OldTemp
    $env:TMP = $OldTmp
}

