@echo off
setlocal
pushd "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\setup_qwen_runtime.ps1"
if errorlevel 1 echo Runtime installation failed. See the error above.
pause
popd
