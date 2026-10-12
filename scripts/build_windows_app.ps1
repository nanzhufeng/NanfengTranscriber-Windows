$ErrorActionPreference = 'Stop'
$projectPath = Split-Path -Parent $PSScriptRoot
Push-Location $projectPath
$originalPath = $env:PATH
try {
    $buildPython = (Get-Command python).Source
    $env:PATH = "$(Split-Path $buildPython);$env:SystemRoot\System32;$env:SystemRoot"
    & $buildPython -m PyInstaller --noconfirm --workpath build --distpath dist_release_current '南枫转写_Windows.spec'
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller build failed.' }
    $applicationPath = Join-Path $projectPath 'dist_release_current/南枫转写'
    New-Item -ItemType Directory -Force (Join-Path $applicationPath 'scripts') | Out-Null
    Copy-Item scripts/setup_qwen_runtime.ps1 (Join-Path $applicationPath 'scripts')
    $setupScript = Join-Path $applicationPath 'scripts/setup_qwen_runtime.ps1'
    [IO.File]::WriteAllText($setupScript, [IO.File]::ReadAllText($setupScript), [Text.UTF8Encoding]::new($true))
    Copy-Item requirements-qwen.txt $applicationPath
    Copy-Item '安装中文精确运行环境_Windows.bat' $applicationPath
    $setupBat = Join-Path $applicationPath '安装中文精确运行环境_Windows.bat'
    [IO.File]::WriteAllText($setupBat, ([IO.File]::ReadAllText($setupBat) -replace '\r?\n', "`r`n"), [Text.UTF8Encoding]::new($false))
} finally {
    $env:PATH = $originalPath
    Pop-Location
}
