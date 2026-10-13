param([string]$RuntimeDirectory = '', [switch]$BootstrapOnly, [switch]$VerifyOnly)
$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$projectPath = Split-Path -Parent $PSScriptRoot
$packaged = Test-Path -LiteralPath (Join-Path $projectPath '南枫转写.exe')
$runtimePath = if ($RuntimeDirectory) { $RuntimeDirectory } elseif ($packaged) {
    Join-Path $env:LOCALAPPDATA 'NanfengTranscriber\runtimes\qwen'
} else { Join-Path $projectPath '.runtime\qwen' }
$pythonPath = Join-Path $runtimePath 'python.exe'
$venvPython = Join-Path $runtimePath 'Scripts\python.exe'
if (-not $packaged -and (Test-Path -LiteralPath $venvPython)) { $pythonPath = $venvPython }
if ($VerifyOnly -and -not (Test-Path -LiteralPath $pythonPath)) { throw 'Python runtime is missing. Run installation first.' }
New-Item -ItemType Directory -Force $runtimePath | Out-Null
if (-not (Test-Path -LiteralPath $pythonPath)) {
    Write-Host 'Downloading independent Python runtime (no system Python required)...'
    $archive = Join-Path $runtimePath 'python-bootstrap.zip'
    try {
        Invoke-WebRequest -UseBasicParsing 'https://www.python.org/ftp/python/3.13.3/python-3.13.3-embed-amd64.zip' -OutFile $archive
        Expand-Archive -LiteralPath $archive -DestinationPath $runtimePath -Force
    } finally { Remove-Item -LiteralPath $archive -Force -ErrorAction SilentlyContinue }
    [IO.File]::WriteAllText((Join-Path $runtimePath 'python313._pth'), "python313.zip`n.`nLib/site-packages`nimport site`n", [Text.UTF8Encoding]::new($false))
}
if (-not $VerifyOnly -and -not (Test-Path -LiteralPath (Join-Path $runtimePath 'Lib/site-packages/pip/__main__.py'))) {
    $bootstrap = Join-Path $runtimePath 'get-pip.py'
    try {
        Invoke-WebRequest -UseBasicParsing 'https://bootstrap.pypa.io/get-pip.py' -OutFile $bootstrap
        & $pythonPath $bootstrap --no-warn-script-location
        if ($LASTEXITCODE -ne 0) { throw 'pip bootstrap failed.' }
    } finally { Remove-Item -LiteralPath $bootstrap -Force -ErrorAction SilentlyContinue }
}
if ($BootstrapOnly) { return }
if (-not $VerifyOnly) {
    Write-Host 'Installing local inference dependencies. GPU libraries require several GB; this runs once.'
    & $pythonPath -m pip install 'torch==2.11.0' --index-url https://download.pytorch.org/whl/cu128
    if ($LASTEXITCODE -ne 0) { throw 'CUDA PyTorch installation failed.' }
    & $pythonPath -m pip install -r (Join-Path $projectPath 'requirements-qwen.txt')
    if ($LASTEXITCODE -ne 0) { throw 'Qwen runtime installation failed.' }
}
$verificationScript = Join-Path $runtimePath ('verify-' + [Guid]::NewGuid().ToString('N') + '.py')
try {
    $verificationCode = @'
from transformers import AutoModelForMultimodalLM, AutoModelForTokenClassification
import torch
print("Qwen runtime ready; CUDA:", torch.cuda.is_available())
'@
    [IO.File]::WriteAllText($verificationScript, $verificationCode, [Text.UTF8Encoding]::new($false))
    & $pythonPath $verificationScript
    if ($LASTEXITCODE -ne 0) { throw 'Qwen runtime verification failed.' }
} finally {
    Remove-Item -LiteralPath $verificationScript -Force -ErrorAction SilentlyContinue
}
[IO.File]::WriteAllText((Join-Path $runtimePath 'runtime.ready'), 'torch=2.11.0;transformers=5.17.0', [Text.UTF8Encoding]::new($false))
Write-Host 'Installation complete. Return to Nanfeng Transcriber and click Start again.'
