param(
    [string]$Version = '',
    [string]$SourceAppPath = '',
    [switch]$ValidateOnly
)

$ErrorActionPreference = 'Stop'

$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
if ($SourceAppPath) {
    $sourceAppDir = Get-Item -LiteralPath $SourceAppPath
} else {
    $currentRelease = Join-Path $projectDir 'dist_release_current'
    $releaseDir = if (Test-Path -LiteralPath (Join-Path $currentRelease '南枫转写/南枫转写.exe')) {
        Get-Item -LiteralPath $currentRelease
    } else {
        Get-ChildItem -LiteralPath $projectDir -Directory -Filter 'dist_release_*' |
            Sort-Object LastWriteTime -Descending |
            Select-Object -First 1
    }

    if (-not $releaseDir) {
        throw 'No dist_release_* directory was found. Build the Windows application first.'
    }

    $sourceAppDir = Get-ChildItem -LiteralPath $releaseDir.FullName -Directory |
        Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName ($_.Name + '.exe')) } |
        Select-Object -First 1

    if (-not $sourceAppDir) {
        throw ('No application folder with matching exe was found in: ' + $releaseDir.FullName)
    }
}
if (-not $sourceAppDir.FullName -or -not (Test-Path -LiteralPath (Join-Path $sourceAppDir.FullName '南枫转写.exe'))) {
    throw 'Installer source must be the built application directory.'
}
$metadataFile = Join-Path $sourceAppDir.FullName '_internal/app/assets/product.json'
if (-not (Test-Path -LiteralPath $metadataFile)) {
    throw 'Built product metadata is missing. Rebuild with scripts/build_windows_app.ps1 first.'
}
$builtProduct = [IO.File]::ReadAllText($metadataFile) | ConvertFrom-Json
$sourceProduct = [IO.File]::ReadAllText((Join-Path $projectDir 'app/assets/product.json')) | ConvertFrom-Json
if ($builtProduct.version -notmatch '^\d+\.\d+\.\d+$' -or $builtProduct.version -ne $sourceProduct.version) {
    throw 'Built and source versions differ. Rebuild the current application before packaging.'
}
if ($Version -and $Version -ne $builtProduct.version) {
    throw 'Requested installer version differs from the built application version.'
}
$Version = $builtProduct.version
if ($ValidateOnly) {
    [pscustomobject]@{
        Version = $Version
        SourceApp = $sourceAppDir.FullName
        InstallerName = "NanfengTranscriber-Windows-v${Version}-Setup.exe"
    } | ConvertTo-Json -Compress
    return
}

$isccCandidates = @(
    (Join-Path $env:LOCALAPPDATA 'Programs\Inno Setup 6\ISCC.exe'),
    (Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6\ISCC.exe'),
    (Join-Path $env:ProgramFiles 'Inno Setup 6\ISCC.exe')
) | Where-Object { $_ -and (Test-Path -LiteralPath $_) }
$iscc = $isccCandidates | Select-Object -First 1
if (-not $iscc) {
    $innoRegistry = Get-ItemProperty `
        'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*', `
        'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*', `
        'HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*' `
        -ErrorAction SilentlyContinue |
        Where-Object { $_.DisplayName -like 'Inno Setup*' -and $_.InstallLocation } |
        Select-Object -First 1
    if ($innoRegistry) {
        $registryCompiler = Join-Path $innoRegistry.InstallLocation 'ISCC.exe'
        if (Test-Path -LiteralPath $registryCompiler) {
            $iscc = $registryCompiler
        }
    }
}
if (-not $iscc) {
    $isccCommand = Get-Command 'ISCC.exe' -ErrorAction SilentlyContinue
    if ($isccCommand) {
        $iscc = $isccCommand.Source
    }
}
if (-not $iscc) {
    throw 'Inno Setup 6 was not found. Install it first: winget install --id JRSoftware.InnoSetup -e'
}

$timestamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$outputDir = Join-Path $projectDir ("WindowsSetup_Inno_$timestamp")
New-Item -ItemType Directory -Force -Path $outputDir | Out-Null

$outputBaseName = "NanfengTranscriber-Windows-v${Version}-Setup"
$issPath = Join-Path $projectDir 'installer\NanfengTranscriber-Windows.iss'
$iconPath = Join-Path $projectDir 'app\assets\nanfeng-transcriber-icon.ico'
$issCompilePath = Join-Path $env:TEMP ("NanfengTranscriber-Windows-$timestamp.iss")
$issContent = [System.IO.File]::ReadAllText($issPath, [System.Text.UTF8Encoding]::new($false))
[System.IO.File]::WriteAllText($issCompilePath, $issContent, [System.Text.UTF8Encoding]::new($true))

try {
    & $iscc `
        "/DMyAppSourceDir=$($sourceAppDir.FullName)" `
        "/DMyOutputDir=$outputDir" `
        "/DMyOutputBaseFilename=$outputBaseName" `
        "/DMyAppVersion=$Version" `
        "/DMySetupIconFile=$iconPath" `
        $issCompilePath
}
finally {
    Remove-Item -LiteralPath $issCompilePath -Force -ErrorAction SilentlyContinue
}

if ($LASTEXITCODE -ne 0) {
    throw ('Inno Setup compilation failed with exit code: ' + $LASTEXITCODE)
}

$setupExe = Join-Path $outputDir ($outputBaseName + '.exe')
if (-not (Test-Path -LiteralPath $setupExe)) {
    throw ('Inno Setup did not create the expected installer: ' + $setupExe)
}
if ((Get-Item -LiteralPath $setupExe).Length -lt 64KB) {
    throw ('The generated installer is unexpectedly small: ' + $setupExe)
}

[pscustomobject]@{
    Compiler = $iscc
    SourceApp = $sourceAppDir.FullName
    InstallerExe = $setupExe
    InstallerBytes = (Get-Item -LiteralPath $setupExe).Length
    Sha256 = (Get-FileHash -LiteralPath $setupExe -Algorithm SHA256).Hash
} | Format-List
