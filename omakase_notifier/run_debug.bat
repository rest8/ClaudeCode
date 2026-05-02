@echo off
REM Double-click this to run with a console window that stays open on error.
REM Use this when launcher.py fails silently — the error message will remain visible.

setlocal
cd /d "%~dp0"

echo [omakase] Python interpreter:
py -c "import sys; print('  ', sys.executable)" 2>nul || python -c "import sys; print('  ', sys.executable)"
echo.

py launcher.py 2>nul
if errorlevel 1 (
    echo.
    echo [omakase] py.exe launcher failed, falling back to python.exe...
    python launcher.py
)

echo.
echo [omakase] launcher exited. Press any key to close this window.
pause >nul
endlocal
