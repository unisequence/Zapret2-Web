[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$venvRoot = Join-Path $projectRoot ".venv"
$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
$bootstrapScript = Join-Path $PSScriptRoot "bootstrap_windows.ps1"
$runScript = Join-Path $projectRoot "run.ps1"

function Test-Python311 {
    param([Parameter(Mandatory = $true)][string]$Launcher)

    $output = & $Launcher -3 -c "import sys; print('Python', sys.version.split()[0]); raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" 2>&1
    $exitCode = $LASTEXITCODE
    $output | ForEach-Object { Write-Host $_ }
    return ($exitCode -eq 0)
}

function Test-VenvPython311 {
    param([Parameter(Mandatory = $true)][string]$Python)

    $output = & $Python -c "import sys; print('Virtual environment:', sys.version.split()[0]); raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" 2>&1
    $exitCode = $LASTEXITCODE
    $output | ForEach-Object { Write-Host $_ }
    return ($exitCode -eq 0)
}

function Refresh-Path {
    $machinePath = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = (@($machinePath, $userPath, $env:Path) | Where-Object { $_ }) -join ";"
}

Write-Host "Zapret2 WebControl — подготовка Windows"
Write-Host "Папка проекта: $projectRoot"

$pythonLauncher = Get-Command py.exe -ErrorAction SilentlyContinue
if (-not $pythonLauncher -or -not (Test-Python311 -Launcher $pythonLauncher.Source)) {
    $winget = Get-Command winget.exe -ErrorAction SilentlyContinue
    if (-not $winget) {
        throw "Не найден Python 3.11+ и недоступен winget. Установите App Installer из Microsoft Store и повторите либо вручную установите Python 3.11+ с https://www.python.org/downloads/windows/."
    }

    Write-Host "Python 3.11+ не найден. Запускаю установку Python 3.13 через WinGet."
    Write-Host "WinGet может запросить подтверждение условий пакета или показать системный запрос разрешения."
    & $winget.Source install --id Python.Python.3.13 --exact --source winget --scope user 2>&1 | ForEach-Object { Write-Host $_ }
    $installExitCode = $LASTEXITCODE
    if ($installExitCode -ne 0) {
        throw "Установка Python через WinGet завершилась с кодом $installExitCode. Исправьте проблему и откройте setup.bat повторно."
    }

    Refresh-Path
    $pythonLauncher = Get-Command py.exe -ErrorAction SilentlyContinue
    if (-not $pythonLauncher -or -not (Test-Python311 -Launcher $pythonLauncher.Source)) {
        throw "Python установлен, но launcher py пока недоступен в этой сессии. Закройте окно, откройте setup.bat повторно или проверьте установку Python вручную."
    }
}

if (Test-Path -LiteralPath (Join-Path $projectRoot ".venv")) {
    if (-not (Test-Path -LiteralPath $venvPython)) {
        throw "Папка .venv уже существует, но в ней нет Scripts\python.exe. Ничего не удалено; переименуйте .venv вручную и повторите установку."
    }
    if (-not (Test-VenvPython311 -Python $venvPython)) {
        throw "В существующем .venv используется Python младше 3.11. Ничего не удалено; переименуйте .venv вручную и повторите установку."
    }
    Write-Host "Виртуальное окружение уже готово."
}
else {
    Write-Host "Создаю виртуальное окружение .venv..."
    & $pythonLauncher.Source -3 -m venv $venvRoot 2>&1 | ForEach-Object { Write-Host $_ }
    $venvExitCode = $LASTEXITCODE
    if ($venvExitCode -ne 0) {
        throw "Не удалось создать виртуальное окружение (код $venvExitCode)."
    }
    if (-not (Test-Path -LiteralPath $venvPython) -or -not (Test-VenvPython311 -Python $venvPython)) {
        throw "Созданное виртуальное окружение не прошло проверку версии Python."
    }
}

Write-Host "Загружаю и проверяю Windows-бандл и ресурсы..."
& powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File $bootstrapScript 2>&1 | ForEach-Object { Write-Host $_ }
$bootstrapExitCode = $LASTEXITCODE
if ($bootstrapExitCode -ne 0) {
    throw "Подготовка Windows-бандла завершилась с кодом $bootstrapExitCode. Запустите setup.bat повторно после устранения ошибки."
}

Write-Host "Установка завершена. Панель запущена по адресу http://127.0.0.1:8787"
Write-Host "Не закрывайте это окно, пока пользуетесь панелью. Для остановки нажмите Ctrl+C."
& powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File $runScript 2>&1 | ForEach-Object { Write-Host $_ }
$runExitCode = $LASTEXITCODE
if ($runExitCode -ne 0) {
    throw "Панель завершилась с кодом $runExitCode."
}
