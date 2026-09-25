[CmdletBinding()]
param(
    [switch]$SkipBundle
)

$ErrorActionPreference = "Stop"
$oldSecurityProtocol = [Net.ServicePointManager]::SecurityProtocol
[Net.ServicePointManager]::SecurityProtocol = $oldSecurityProtocol -bor [Net.SecurityProtocolType]::Tls12

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$bundleRoot = Join-Path $projectRoot "vendor\zapret-win-bundle"
$blobRoot = Join-Path $projectRoot "runtime\blobs"
$bundleCommit = "6eb463a6758fb48cd101bc55dfd057e6e9d98af1"
$bundleMarker = ".zapret2-webcontrol-commit"
$requiredBundleFiles = @(
    "zapret-winws\winws2.exe",
    "zapret-winws\lua\zapret-lib.lua",
    "zapret-winws\lua\zapret-antidpi.lua",
    "zapret-winws\lua\zapret-auto.lua",
    "zapret-winws\windivert.filter\windivert_part.discord_media.txt",
    "zapret-winws\windivert.filter\windivert_part.stun.txt",
    "blockcheck\zapret2\blockcheck2.sh",
    "cygwin\bin\bash.exe",
    "cygwin\bin\cygpath.exe"
)

function Test-BundleFiles {
    param([Parameter(Mandatory = $true)][string]$Root)

    foreach ($relativePath in $requiredBundleFiles) {
        if (-not (Test-Path -LiteralPath (Join-Path $Root $relativePath))) {
            throw "В Windows-бандле отсутствует обязательный файл: $relativePath"
        }
    }
}

function Invoke-GitChecked {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)

    & git @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Git завершился с кодом ${LASTEXITCODE}: git $($Arguments -join ' ')"
    }
}

function Install-ZapretBundle {
    if (-not (Test-Path -LiteralPath $bundleRoot)) {
        $temporaryRoot = Join-Path ([IO.Path]::GetTempPath()) ("zapret2-webcontrol-bundle-" + [Guid]::NewGuid().ToString("N"))
        $archivePath = Join-Path $temporaryRoot "bundle.zip"
        $extractRoot = Join-Path $temporaryRoot "extracted"
        try {
            New-Item -ItemType Directory -Path $extractRoot -Force | Out-Null
            Write-Host "Скачиваю закреплённый Windows-бандл..."
            Invoke-WebRequest -Uri "https://codeload.github.com/bol-van/zapret-win-bundle/zip/$bundleCommit" -OutFile $archivePath -UseBasicParsing
            Expand-Archive -LiteralPath $archivePath -DestinationPath $extractRoot -Force

            $archiveRoots = @(Get-ChildItem -LiteralPath $extractRoot -Directory)
            if ($archiveRoots.Count -ne 1) {
                throw "Архив Windows-бандла имеет неожиданный формат."
            }
            $sourceRoot = $archiveRoots[0].FullName
            Test-BundleFiles -Root $sourceRoot
            Set-Content -LiteralPath (Join-Path $sourceRoot $bundleMarker) -Value $bundleCommit -Encoding Ascii -NoNewline

            New-Item -ItemType Directory -Path (Split-Path $bundleRoot) -Force | Out-Null
            Move-Item -LiteralPath $sourceRoot -Destination $bundleRoot
        }
        finally {
            if (Test-Path -LiteralPath $temporaryRoot) {
                Remove-Item -LiteralPath $temporaryRoot -Recurse -Force
            }
        }
    }
    elseif (Test-Path -LiteralPath (Join-Path $bundleRoot $bundleMarker)) {
        $currentCommit = (Get-Content -LiteralPath (Join-Path $bundleRoot $bundleMarker) -Raw).Trim()
        if ($currentCommit -ne $bundleCommit) {
            throw "В $bundleRoot находится ZIP-бандл другой версии ($currentCommit). Он не будет перезаписан автоматически."
        }
    }
    elseif (Test-Path -LiteralPath (Join-Path $bundleRoot ".git")) {
        if (-not (Get-Command git.exe -ErrorAction SilentlyContinue)) {
            throw "Для проверки существующего Git-бандла нужен Git for Windows. Новая установка из ZIP Git не требует."
        }

        $currentCommit = (& git -C $bundleRoot rev-parse HEAD).Trim()
        if ($LASTEXITCODE -ne 0) {
            throw "Не удалось определить commit Windows-бандла."
        }
        if ($currentCommit -ne $bundleCommit) {
            $dirty = & git -C $bundleRoot status --porcelain
            if ($LASTEXITCODE -ne 0) {
                throw "Не удалось проверить состояние Windows-бандла."
            }
            if ($dirty) {
                throw "В Windows-бандле есть локальные изменения; bootstrap не будет их перезаписывать."
            }
            Invoke-GitChecked -Arguments @(
                "-C", $bundleRoot, "fetch", "origin", $bundleCommit
            )
            Invoke-GitChecked -Arguments @(
                "-C", $bundleRoot, "checkout", "--detach", $bundleCommit
            )
        }
    }
    else {
        throw "Каталог $bundleRoot уже существует, но его версия не подтверждена. Переименуйте его вручную и повторите bootstrap."
    }

    Test-BundleFiles -Root $bundleRoot
    Write-Host "Windows-бандл готов: $bundleCommit"
}

function Install-VerifiedBlob {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Uri,
        [Parameter(Mandatory = $true)][string]$Sha256
    )

    $target = Join-Path $blobRoot $Name
    if (Test-Path -LiteralPath $target) {
        $existingHash = (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash
        if ($existingHash -eq $Sha256) {
            Write-Host "Payload уже проверен: $Name"
            return
        }
    }

    $temporary = "$target.download"
    try {
        Invoke-WebRequest -Uri $Uri -OutFile $temporary -UseBasicParsing
        $downloadedHash = (Get-FileHash -LiteralPath $temporary -Algorithm SHA256).Hash
        if ($downloadedHash -ne $Sha256) {
            throw "SHA-256 не совпал для $Name. Ожидался $Sha256, получен $downloadedHash."
        }
        Move-Item -LiteralPath $temporary -Destination $target -Force
        Write-Host "Payload установлен: $Name"
    }
    finally {
        if (Test-Path -LiteralPath $temporary) {
            Remove-Item -LiteralPath $temporary -Force
        }
    }
}

if (-not $SkipBundle) {
    Install-ZapretBundle
}

New-Item -ItemType Directory -Path $blobRoot -Force | Out-Null

$flowsealCommit = "865da4f4c3659523bf79bc6edf0446e7d7969614"
$openwrtCommit = "1b04a87558ec7965bfed0ef7fb557997872dd699"
$resources = @(
    @{
        Name = "quic_initial_steamcommunity_com.bin"
        Uri = "https://raw.githubusercontent.com/Flowseal/zapret-discord-youtube/$flowsealCommit/bin/quic_initial_steamcommunity_com.bin"
        Sha256 = "2FE18B3BD20807D36704D0B072092EE49AE84EDCA907A4420AB9A0F0F28FDDCF"
    },
    @{
        Name = "stun2.bin"
        Uri = "https://raw.githubusercontent.com/Flowseal/zapret-discord-youtube/$flowsealCommit/bin/stun2.bin"
        Sha256 = "B7C2497496039C541F7337AC8536813F0A1CF52363AB2FAA5213B7816D458813"
    },
    @{
        Name = "quic_initial_4pda_to.bin"
        Uri = "https://raw.githubusercontent.com/Flowseal/zapret-discord-youtube/$flowsealCommit/bin/quic_initial_4pda_to.bin"
        Sha256 = "E065870CB0D13152E6132807BBF42218A9E7CD8D96F5602B61674CC540F3A56E"
    },
    @{
        Name = "tls_clienthello_www_onetrust_com.bin"
        Uri = "https://raw.githubusercontent.com/remittor/zapret-openwrt/$openwrtCommit/zapret/files/fake/tls_clienthello_www_onetrust_com.bin"
        Sha256 = "4EE0870ABE0A0128600B0095189987BA1D210DAE8BF963BC725AFF49CF922624"
    }
)

foreach ($resource in $resources) {
    Install-VerifiedBlob @resource
}

Write-Host "Ресурсы Windows готовы. Запустите .\run.ps1"
