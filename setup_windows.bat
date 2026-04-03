@echo off
echo === iFOREX Trading Bot - Windows Setup ===
echo.

REM Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python is not installed. Download from https://www.python.org/downloads/
    pause
    exit /b 1
)

REM Create virtual environment
echo Creating virtual environment...
python -m venv venv
call venv\Scripts\activate.bat

REM Install dependencies
echo Installing dependencies...
pip install -r requirements.txt

REM Install Playwright browsers
echo Installing Playwright Chromium browser...
playwright install chromium

REM Create .env from example if not exists
if not exist .env (
    copy .env.example .env
    echo.
    echo [IMPORTANT] .env file created. Edit it with your iFOREX credentials:
    echo   notepad .env
)

echo.
echo === Setup complete! ===
echo.
echo Next steps:
echo   1. Edit .env with your iFOREX email and password
echo   2. Run: python main.py
echo.
pause
