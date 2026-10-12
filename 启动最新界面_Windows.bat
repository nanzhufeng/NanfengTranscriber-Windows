@echo off
setlocal
chcp 65001 >nul
pushd "%~dp0"
set "PYTHONUTF8=1"
where python >nul 2>&1
if errorlevel 1 (
    echo 未找到 Python，请先安装 Python 和 requirements.txt 中的依赖。
    pause
    popd
    exit /b 1
)
if /i "%~1"=="--check" (
    python -c "import PySide6; import app.main; print('Launcher check OK')"
    popd
    exit /b
)
if not exist ".runtime" mkdir ".runtime"
echo 正在启动南枫转写最新界面……
python "%~dp0start.py" >"%~dp0.runtime\latest-launch.log" 2>&1
set "TRANSCRIBER_EXIT=%ERRORLEVEL%"
if not "%TRANSCRIBER_EXIT%"=="0" (
    echo 启动或运行失败，详细信息如下：
    type "%~dp0.runtime\latest-launch.log"
    pause
)
popd
exit /b %TRANSCRIBER_EXIT%
