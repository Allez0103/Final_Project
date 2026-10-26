param([switch]$FullWorkflow)
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$ReportDirectory = Join-Path $Root 'runtime-data/native-validation'
$Package = Get-Content -LiteralPath (Join-Path $ReportDirectory 'portable-package-v19.json') -Raw | ConvertFrom-Json
$Unpacked = [System.IO.Path]::GetFullPath($Package.unpacked)
$Allowed = [System.IO.Path]::GetFullPath((Join-Path $Root 'build'))
if (-not $Unpacked.StartsWith($Allowed + [System.IO.Path]::DirectorySeparatorChar)) { throw 'Unexpected package path' }
$Exe = Join-Path $Unpacked 'PA2.exe'
if ((Get-FileHash -LiteralPath $Exe -Algorithm SHA256).Hash.ToLowerInvariant() -ne $Package.executable_sha256) { throw 'Packaged executable changed' }
$Keys = @('PATH','PYTHONPATH','PA2_DATA_ROOT','PA2_DATABASE_URL','PA2_SMOKE_PROJECT','PA2_SMOKE_SETTINGS','PA2_UI_VERIFY_PREFLIGHT','IMAGEIO_FFMPEG_EXE')
$Saved = @{}
foreach ($Key in $Keys) { $Saved[$Key] = [Environment]::GetEnvironmentVariable($Key, 'Process') }
function Invoke-Check([string]$Flag, [string]$Name) {
    $Output = Join-Path $ReportDirectory ($Name + '.json')
    $Process = Start-Process -FilePath $Exe -ArgumentList @($Flag,$Output) -WorkingDirectory $Unpacked -WindowStyle Hidden -Wait -PassThru -RedirectStandardOutput (Join-Path $ReportDirectory ($Name + '.stdout.log')) -RedirectStandardError (Join-Path $ReportDirectory ($Name + '.stderr.log'))
    if ($Process.ExitCode -ne 0) { throw "$Name failed: $($Process.ExitCode)" }
    $Result = Get-Content -LiteralPath $Output -Raw | ConvertFrom-Json
    if (-not $Result.ok) { throw "$Name reported failure" }
    Write-Output "$Name passed"
}
try {
    $env:PATH = "$env:SystemRoot\System32;$env:SystemRoot"
    $env:PYTHONPATH = $null
    $env:PA2_DATABASE_URL = $null
    $env:PA2_SMOKE_PROJECT = $null
    $env:PA2_SMOKE_SETTINGS = $null
    $env:PA2_UI_VERIFY_PREFLIGHT = $null
    $env:IMAGEIO_FFMPEG_EXE = $null
    $env:PA2_DATA_ROOT = Join-Path $Root ('runtime-data/portable-clean-v19-' + [guid]::NewGuid().ToString('N'))
    Invoke-Check '--gui-smoke' 'portable-gui-smoke-v19'
    Invoke-Check '--native-smoke' 'portable-native-smoke-v19'
    $Ffmpeg = (Get-ChildItem -LiteralPath (Join-Path $Unpacked '_internal/imageio_ffmpeg/binaries') -Filter '*.exe' | Select-Object -First 1).FullName
    $Clip = Join-Path $ReportDirectory 'portable-encode-v19.mp4'
    if (Test-Path -LiteralPath $Clip) { throw 'Existing encoder verification clip' }
    & $Ffmpeg -hide_banner -loglevel error -f lavfi -i 'color=c=blue:s=320x180:r=30' -t 1 -c:v libx264 -pix_fmt yuv420p $Clip
    if ($LASTEXITCODE -ne 0) { throw 'Portable encoder failed' }
    $Decode = & $Ffmpeg -hide_banner -loglevel error -nostats -progress pipe:1 -i $Clip -f null -
    if ($LASTEXITCODE -ne 0 -or -not ($Decode -match '^frame=30$')) { throw 'Portable full decode failed' }
    $Decode | Out-File -LiteralPath (Join-Path $ReportDirectory 'portable-encode-v19.log') -Encoding utf8
    if ($FullWorkflow) {
        $env:PA2_DATA_ROOT = Join-Path $Root 'runtime-data/end-to-end-v19-final'
        $env:PA2_SMOKE_PROJECT = '7ff36dbc-4826-455d-9a14-2d99f2572641'
        $env:PA2_SMOKE_SETTINGS = Join-Path $ReportDirectory 'planning-v17-final.json'
        Invoke-Check '--ui-v19-smoke' 'ui-v19-packaged-final'
    }
    Write-Output "Verified EXE: $Exe"
} finally {
    foreach ($Key in $Keys) { [Environment]::SetEnvironmentVariable($Key,$Saved[$Key],'Process') }
}
