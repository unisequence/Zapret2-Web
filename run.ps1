$ErrorActionPreference = "Stop"

$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    $python = "py"
}

$env:PYTHONPATH = Join-Path $PSScriptRoot "app"
& $python -m zapret2_webcontrol

