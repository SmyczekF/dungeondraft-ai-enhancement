# Launch a native map through Dungeondraft's installed file-argument entry point.
# Does not stop another editor, create map dimensions, or send UI input.
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$MapPath,
    [string]$ExecutablePath = (Join-Path $env:ProgramFiles 'Dungeondraft\Dungeondraft.exe'),
    [string]$CopyTo,
    [string]$LogDirectory,
    [switch]$ShowWindow
)

$ErrorActionPreference = 'Stop'
$editorLogPath = $null
$mapCopySource = $null
if ($env:OS -ne 'Windows_NT') { throw 'This launcher is for Windows.' }
$nativeMapPath = (Resolve-Path -LiteralPath $MapPath).ProviderPath
if ([IO.Path]::GetExtension($nativeMapPath) -ine '.dungeondraft_map' -or
    -not (Test-Path -LiteralPath $nativeMapPath -PathType Leaf)) {
    throw 'MapPath must be an existing native .dungeondraft_map file.'
}
$nativeMap = Get-Content -LiteralPath $nativeMapPath -Raw | ConvertFrom-Json
if ($null -eq $nativeMap.world.levels -or $null -eq $nativeMap.world.width -or $null -eq $nativeMap.world.height) {
    throw 'MapPath lacks the native world, dimensions or levels.'
}
$editorExecutable = (Resolve-Path -LiteralPath $ExecutablePath).ProviderPath
if (-not (Test-Path -LiteralPath $editorExecutable -PathType Leaf) -or
    [IO.Path]::GetFileName($editorExecutable) -ine 'Dungeondraft.exe') {
    throw 'ExecutablePath must point to the installed Dungeondraft.exe.'
}
if (@(Get-Process -Name Dungeondraft -ErrorAction SilentlyContinue).Count -gt 0) {
    throw 'Dungeondraft is already running. Close it yourself before launching another map.'
}
if ($CopyTo) {
    $mapCopyPath = [IO.Path]::GetFullPath($CopyTo)
    if ([IO.Path]::GetExtension($mapCopyPath) -ine '.dungeondraft_map' -or
        (Test-Path -LiteralPath $mapCopyPath) -or
        -not (Test-Path -LiteralPath ([IO.Path]::GetDirectoryName($mapCopyPath)) -PathType Container)) {
        throw 'CopyTo must be a new .dungeondraft_map path in an existing directory.'
    }
    $mapCopySource = $nativeMapPath
    $nativeMapPath = $mapCopyPath
}
$launchOptions = @{
    FilePath = $editorExecutable
    ArgumentList = '"' + $nativeMapPath + '"'
    WorkingDirectory = [IO.Path]::GetDirectoryName($editorExecutable)
    WindowStyle = 'Hidden'
    PassThru = $true
}
if ($ShowWindow) { $launchOptions.WindowStyle = 'Normal' }
if ($LogDirectory) {
    $editorLogPath = [IO.Path]::GetFullPath($LogDirectory)
    if (Test-Path -LiteralPath $editorLogPath) {
        if (-not (Test-Path -LiteralPath $editorLogPath -PathType Container) -or
            @(Get-ChildItem -LiteralPath $editorLogPath -Force).Count -gt 0) {
            throw 'LogDirectory must be new or empty; existing logs are never overwritten.'
        }
    } else {
        New-Item -ItemType Directory -Path $editorLogPath | Out-Null
    }
    $launchOptions.RedirectStandardOutput = Join-Path $editorLogPath 'dungeondraft.stdout.log'
    $launchOptions.RedirectStandardError = Join-Path $editorLogPath 'dungeondraft.stderr.log'
}
if ($mapCopySource) { Copy-Item -LiteralPath $mapCopySource -Destination $nativeMapPath }
$editorProcess = Start-Process @launchOptions
[pscustomobject]@{
    ProcessId = $editorProcess.Id
    MapPath = $nativeMapPath
    SizeTiles = @($nativeMap.world.width, $nativeMap.world.height)
    LogDirectory = $editorLogPath
    Ready = 'Check MCP ping and get_status; process launch alone does not prove map readiness.'
}
