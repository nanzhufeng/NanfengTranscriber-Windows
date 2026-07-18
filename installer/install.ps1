$ErrorActionPreference = 'Stop'

$payload = Join-Path $PSScriptRoot 'payload.zip'
if (-not (Test-Path -LiteralPath $payload)) {
    throw 'payload.zip is missing.'
}

$tempExtract = Join-Path $env:TEMP ('nanfeng_transcriber_install_' + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force -Path $tempExtract | Out-Null

try {
    Expand-Archive -LiteralPath $payload -DestinationPath $tempExtract -Force
    $sourceDir = Get-ChildItem -LiteralPath $tempExtract -Directory | Select-Object -First 1
    if (-not $sourceDir) {
        throw 'No application folder found in payload.zip.'
    }

    $appName = $sourceDir.Name
    $installRoot = Join-Path $env:LOCALAPPDATA 'Programs'
    $installDir = Join-Path $installRoot $appName
    New-Item -ItemType Directory -Force -Path $installDir | Out-Null

    Get-ChildItem -LiteralPath $sourceDir.FullName -Force | ForEach-Object {
        Copy-Item -LiteralPath $_.FullName -Destination $installDir -Recurse -Force
    }

    $exePath = Join-Path $installDir ($appName + '.exe')
    if (-not (Test-Path -LiteralPath $exePath)) {
        throw ('Main executable was not installed: ' + $exePath)
    }

    $shell = New-Object -ComObject WScript.Shell

    $desktopShortcut = Join-Path ([Environment]::GetFolderPath('Desktop')) ($appName + '.lnk')
    $shortcut = $shell.CreateShortcut($desktopShortcut)
    $shortcut.TargetPath = $exePath
    $shortcut.WorkingDirectory = $installDir
    $shortcut.Description = $appName
    $shortcut.Save()

    $startMenuDir = Join-Path ([Environment]::GetFolderPath('Programs')) '南枫'
    New-Item -ItemType Directory -Force -Path $startMenuDir | Out-Null
    $startShortcut = Join-Path $startMenuDir ($appName + '.lnk')
    $shortcut = $shell.CreateShortcut($startShortcut)
    $shortcut.TargetPath = $exePath
    $shortcut.WorkingDirectory = $installDir
    $shortcut.Description = $appName
    $shortcut.Save()

    Start-Process -FilePath $exePath -WorkingDirectory $installDir

    Add-Type -AssemblyName System.Windows.Forms
    [System.Windows.Forms.MessageBox]::Show(
        "Install completed.`n`nDesktop and Start Menu shortcuts were created.`nInstall path: $installDir",
        "$appName Setup",
        [System.Windows.Forms.MessageBoxButtons]::OK,
        [System.Windows.Forms.MessageBoxIcon]::Information
    ) | Out-Null
}
catch {
    Add-Type -AssemblyName System.Windows.Forms
    [System.Windows.Forms.MessageBox]::Show(
        ('Install failed: ' + $_.Exception.Message),
        'Setup failed',
        [System.Windows.Forms.MessageBoxButtons]::OK,
        [System.Windows.Forms.MessageBoxIcon]::Error
    ) | Out-Null
    exit 1
}
finally {
    if (Test-Path -LiteralPath $tempExtract) {
        Remove-Item -LiteralPath $tempExtract -Recurse -Force -ErrorAction SilentlyContinue
    }
}
