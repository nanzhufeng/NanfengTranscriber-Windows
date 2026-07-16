@echo off
setlocal
pushd "%~dp0"
set "LOG=%~dp0runtime-log.txt"
echo [%date% %time%] source test started> "%LOG%"
echo cwd=%CD%>> "%LOG%"
echo python check:>> "%LOG%"
python --version>> "%LOG%" 2>&1
echo starting source app, keep this console open...
echo log file: %LOG%
python "%~dp0start.py"
echo.
echo source app exited. Check runtime-log.txt for details.
pause
popd
