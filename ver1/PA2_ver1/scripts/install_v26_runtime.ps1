$ErrorActionPreference = 'Stop'
$ProjectRoot = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$StagedRuntime = [IO.Path]::GetFullPath((Join-Path $ProjectRoot 'build/distribution-v26/PA2'))
$PreviousRuntime = [IO.Path]::GetFullPath((Join-Path $ProjectRoot 'build/previous-release-v26-top-landscape-20261022'))
foreach ($PathToCheck in @($StagedRuntime, $PreviousRuntime)) {
    if (-not $PathToCheck.StartsWith($ProjectRoot + [IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)) {
        throw "Runtime target is outside project: $PathToCheck"
    }
}
if (Test-Path -LiteralPath $PreviousRuntime) { throw 'Backup exists; refusing overwrite.' }
foreach ($RuntimeName in @('PA2.exe','_internal')) {
    if (-not (Test-Path -LiteralPath (Join-Path $StagedRuntime $RuntimeName))) { throw "Missing staged runtime: $RuntimeName" }
}
$Running = Get-Process -Name PA2 -ErrorAction SilentlyContinue | Where-Object {
    $_.Path -and ([IO.Path]::GetFullPath($_.Path) -eq (Join-Path $ProjectRoot 'PA2.exe') -or
                  [IO.Path]::GetFullPath($_.Path) -eq (Join-Path $StagedRuntime 'PA2.exe'))
}
if ($Running) { throw 'Close PA2 before updating the runtime.' }
New-Item -ItemType Directory -Path $PreviousRuntime | Out-Null
foreach ($RuntimeName in @('PA2.exe','_internal')) {
    $InstalledRuntime = [IO.Path]::GetFullPath((Join-Path $ProjectRoot $RuntimeName))
    $BackupRuntime = [IO.Path]::GetFullPath((Join-Path $PreviousRuntime $RuntimeName))
    if (-not $InstalledRuntime.StartsWith($ProjectRoot + [IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)) {
        throw 'Invalid runtime target'
    }
    if (Test-Path -LiteralPath $InstalledRuntime) { Move-Item -LiteralPath $InstalledRuntime -Destination $BackupRuntime }
    Move-Item -LiteralPath (Join-Path $StagedRuntime $RuntimeName) -Destination $InstalledRuntime
}
Write-Output "Updated: $(Join-Path $ProjectRoot 'PA2.exe')"
Write-Output "Recoverable previous runtime: $PreviousRuntime"
