@echo off
REM Launch the Omakase Notifier admin UI.
setlocal
cd /d "%~dp0\.."

if not exist ".venv\Scripts\python.exe" (
    echo [omakase] virtualenv not found. Run scripts\install_windows.ps1 first.
    pause
    exit /b 1
)

if not exist "config.yaml" (
    echo [omakase] config.yaml not found. Copy config.example.yaml and edit it.
    pause
    exit /b 1
)

set PYTHONPATH=src
".venv\Scripts\pythonw.exe" -m omakase_notifier
endlocal
