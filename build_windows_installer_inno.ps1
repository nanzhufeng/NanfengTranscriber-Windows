param(
    [string]$Version = '1.0.0'
)

$ErrorActionPreference = 'Stop'

$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$releaseDir = Get-ChildItem -LiteralPath $projectDir -Directory -Filter 'dist_release_*' |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1

if (-not $releaseDir) {
    throw 'No dist_release_* directory was found. Build the Windows application first.'
}

$sourceAppDir = Get-ChildItem -LiteralPath $releaseDir.FullName -Directory |
    Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName ($_.Name + '.exe')) } |
    Select-Object -First 1

if (-not $sourceAppDir) {
    throw ('No application folder with matching exe was found in: ' + $releaseDir.FullName)
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

$outputBaseName = "NanfengTranscriber_Windows_v${Version}_Setup_${timestamp}"
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
if ((Get-Item -LiteralPath $setupExe).Length -lt 1MB) {
    throw ('The generated installer is unexpectedly small: ' + $setupExe)
}

[pscustomobject]@{
    Compiler = $iscc
    SourceApp = $sourceAppDir.FullName
    InstallerExe = $setupExe
    InstallerBytes = (Get-Item -LiteralPath $setupExe).Length
    Sha256 = (Get-FileHash -LiteralPath $setupExe -Algorithm SHA256).Hash
} | Format-List
