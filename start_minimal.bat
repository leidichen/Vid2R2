@echo off
cd /d "%~dp0"

if exist ".venv\Scripts\pythonw.exe" (
    start "" /B ".venv\Scripts\pythonw.exe" minimal_uploader.py
    exit /b
)

where pythonw >nul 2>nul
if %errorlevel%==0 (
    start "" /B pythonw minimal_uploader.py
    exit /b
)

where pyw >nul 2>nul
if %errorlevel%==0 (
    start "" /B pyw -3 minimal_uploader.py
    exit /b
)

echo 未找到可用的 pythonw/pyw，请先安装 Python 或创建 .venv。
pause
