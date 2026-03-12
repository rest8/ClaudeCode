@echo off
echo ==========================================
echo   Omakase Auto-Booker - Build for Windows
echo ==========================================
echo.

REM Install dependencies
echo Installing dependencies...
pip install -r requirements.txt
if errorlevel 1 (
    echo Failed to install dependencies.
    pause
    exit /b 1
)

REM Install Playwright browsers
echo Installing Playwright Chromium...
playwright install chromium
if errorlevel 1 (
    echo Failed to install Playwright browsers.
    pause
    exit /b 1
)

REM Build .exe
echo Building executable...
pyinstaller omakase_booker.spec --noconfirm
if errorlevel 1 (
    echo Build failed.
    pause
    exit /b 1
)

echo.
echo ==========================================
echo   Build complete!
echo   Output: dist\OmakaseBooker.exe
echo ==========================================
echo.
echo NOTE: config.yaml must be placed in the same
echo directory as OmakaseBooker.exe before running.
echo.
pause
