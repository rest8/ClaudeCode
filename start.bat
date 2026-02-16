@echo off
cd /d "%~dp0"
echo Time Manager を起動しています...
pip install pywebview >nul 2>&1
python app.py
pause
