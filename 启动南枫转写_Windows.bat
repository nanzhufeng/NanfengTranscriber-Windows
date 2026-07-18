@echo off
setlocal
cd /d "%~dp0"
set "LOG=%~dp0startup-log.txt"
echo Starting Nanfeng Transcriber Windows... > "%LOG%"
echo Log file: %LOG% >> "%LOG%"

for /f "delims=" %%P in ('where.exe pythonw.exe 2^>nul') do (
    start "" "%%P" "%~dp0start.py"
    exit /b
)

echo pythonw.exe was not found, using visible Python fallback. >> "%LOG%"
start "" python "%~dp0start.py"
