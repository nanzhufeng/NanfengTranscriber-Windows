$ErrorActionPreference = 'Stop'

$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$releaseDir = Get-ChildItem -LiteralPath $projectDir -Directory -Filter 'dist_release_*' |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1

if (-not $releaseDir) {
    throw 'No dist_release_* directory was found.'
}

$sourceAppDir = Get-ChildItem -LiteralPath $releaseDir.FullName -Directory |
    Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName ($_.Name + '.exe')) } |
    Select-Object -First 1

if (-not $sourceAppDir) {
    throw ('No application folder with matching exe was found in: ' + $releaseDir.FullName)
}

$appName = $sourceAppDir.Name
$timestamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$installerOutDir = Join-Path $projectDir "WindowsSetup_$timestamp"
New-Item -ItemType Directory -Force -Path $installerOutDir | Out-Null

$safeStage = Join-Path $env:TEMP "nzf_vtt_installer_$timestamp"
$safePackage = Join-Path $safeStage 'package'
New-Item -ItemType Directory -Force -Path $safePackage | Out-Null

$payloadSource = Join-Path $safePackage $appName
Copy-Item -LiteralPath $sourceAppDir.FullName -Destination $payloadSource -Recurse -Force

$readme = Get-ChildItem -LiteralPath $projectDir -File -Filter 'Windows*.txt' | Select-Object -First 1
if ($readme) {
    Copy-Item -LiteralPath $readme -Destination (Join-Path $payloadSource 'Windows安装说明.txt') -Force
}

$payloadZip = Join-Path $safeStage 'payload.zip'
Compress-Archive -LiteralPath $payloadSource -DestinationPath $payloadZip -Force

Copy-Item -LiteralPath (Join-Path $projectDir 'installer\install.cmd') -Destination (Join-Path $safeStage 'install.cmd') -Force
Copy-Item -LiteralPath (Join-Path $projectDir 'installer\install.ps1') -Destination (Join-Path $safeStage 'install.ps1') -Force

$setupTemp = Join-Path $safeStage 'NanzhufengVideoTranscriberSetup.exe'
$sedPath = Join-Path $safeStage 'installer.sed'
$sed = @"
[Version]
Class=IEXPRESS
SEDVersion=3
[Options]
PackagePurpose=InstallApp
ShowInstallProgramWindow=0
HideExtractAnimation=0
UseLongFileName=1
InsideCompressed=0
CAB_FixedSize=0
CAB_ResvCodeSigning=0
RebootMode=N
InstallPrompt=
DisplayLicense=
FinishMessage=
TargetName=$setupTemp
FriendlyName=Nanzhufeng Video Transcriber Setup
AppLaunched=install.cmd
PostInstallCmd=<None>
AdminQuietInstCmd=install.cmd
UserQuietInstCmd=install.cmd
SourceFiles=SourceFiles
[Strings]
FILE0="payload.zip"
FILE1="install.cmd"
FILE2="install.ps1"
[SourceFiles]
SourceFiles0=$safeStage\
[SourceFiles0]
%FILE0%=
%FILE1%=
%FILE2%=
"@
Set-Content -LiteralPath $sedPath -Value $sed -Encoding ASCII

$iexpress = Join-Path $env:WINDIR 'System32\iexpress.exe'
if (-not (Test-Path -LiteralPath $iexpress)) {
    throw ('IExpress was not found: ' + $iexpress)
}

$iexpressProcess = Start-Process -FilePath $iexpress -ArgumentList @('/N', '/Q', $sedPath) -Wait -PassThru -WindowStyle Hidden
if (-not (Test-Path -LiteralPath $setupTemp)) {
    throw ('IExpress did not create setup exe. Exit code: ' + $iexpressProcess.ExitCode + '; target: ' + $setupTemp)
}
$setupTempInfo = Get-Item -LiteralPath $setupTemp
if ($setupTempInfo.Length -lt 1048576) {
    throw ('IExpress created an invalid setup exe. Exit code: ' + $iexpressProcess.ExitCode + '; bytes: ' + $setupTempInfo.Length)
}

$setupFinal = Join-Path $installerOutDir ($appName + '_Setup.exe')
Copy-Item -LiteralPath $setupTemp -Destination $setupFinal -Force

$installReadme = Join-Path $installerOutDir 'Install-Readme.txt'
@"
Nanzhufeng Video Transcriber Windows setup package

How to install:
1. Extract the whole zip package.
2. Double click "$appName`_Setup.exe".
3. The installer creates Desktop and Start Menu shortcuts.
4. Default install path: %LOCALAPPDATA%\Programs\$appName

Notes:
- This is a clickable setup package, not the portable zip.
- The first medium model run may need internet access to download model files.
- If CUDA / cuBLAS / cuDNN is unavailable, the app falls back to CPU.
"@ | Set-Content -LiteralPath $installReadme -Encoding UTF8

$zipFinal = Join-Path $projectDir ("${appName}_Windows_Click_Setup_$timestamp.zip")
Compress-Archive -LiteralPath $setupFinal, $installReadme -DestinationPath $zipFinal -Force

[pscustomobject]@{
    InstallerExe = $setupFinal
    ZipPackage = $zipFinal
    PayloadBytes = (Get-Item -LiteralPath $payloadZip).Length
    InstallerBytes = (Get-Item -LiteralPath $setupFinal).Length
    ZipBytes = (Get-Item -LiteralPath $zipFinal).Length
} | Format-List
