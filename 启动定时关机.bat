@echo off
cd /d "%~dp0"
where pythonw >nul 2>nul
if errorlevel 1 (
    echo 未找到 pythonw，请先安装 Python 3。
    pause
    exit /b 1
)
start "" pythonw "%~dp0auto_shutdown.py"
