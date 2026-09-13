param([string[]]$MediaRoot = @(), [int]$Port = 8765, [switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
$projectDir = $PSScriptRoot
$pythonExe = Join-Path $projectDir '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonExe)) {
    $launcher = Get-Command python -ErrorAction SilentlyContinue
    if (-not $launcher) {
        Write-Host 'Нужен Python 3.10+: https://www.python.org/downloads/windows/'
        exit 1
    }
    & $launcher.Source -m venv (Join-Path $projectDir '.venv')
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
& $pythonExe -c "import importlib.util, sys; sys.exit(0 if all(importlib.util.find_spec(m) for m in ('frameproof','psutil','numpy')) else 1)"
if ($LASTEXITCODE -ne 0) {
    Write-Host 'Устанавливаем зависимости в .venv приложения.'
    & $pythonExe -m pip install ($projectDir + '[web]')
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
$portableBin = Get-ChildItem -LiteralPath (Join-Path $projectDir 'tools') -Filter ffmpeg.exe -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty DirectoryName
if ($portableBin) { $env:PATH = $portableBin + [IO.Path]::PathSeparator + $env:PATH }
$arguments = @('-m','frameproof','web','--port',"$Port",'--data-dir',(Join-Path $projectDir '.web-data'))
foreach ($mediaDir in $MediaRoot) { $arguments += @('--media-root', $mediaDir) }
if ($NoBrowser) { $arguments += '--no-browser' }
& $pythonExe @arguments
exit $LASTEXITCODE
