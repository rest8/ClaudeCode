@echo off
cd /d "%~dp0"
echo Starting Time Manager...
pip install pywebview >nul 2>&1
python app.py
pause
