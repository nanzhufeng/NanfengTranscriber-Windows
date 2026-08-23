@echo off
setlocal
pushd "%~dp0"

set "LOG=%~dp0runtime-log.txt"
echo [%date% %time%] settings test started> "%LOG%"
echo cwd=%CD%>> "%LOG%"
python --version>> "%LOG%" 2>&1

echo Starting Nanfeng Transcriber source test...
echo Close the app to return here. Log: %LOG%
python "%~dp0start.py"

echo.
echo App exited. Check runtime-log.txt if there was an error.
pause
popd
