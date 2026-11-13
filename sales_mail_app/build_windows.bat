@echo off
rem Build SalesMailer.exe (Windows). Requires Python 3.10+ from python.org.
cd /d %~dp0
if not exist .venv py -3 -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements-dev.txt
pyinstaller --noconfirm --onefile --windowed --name SalesMailer --collect-submodules anthropic run_app.py
echo.
echo Done: dist\SalesMailer.exe
pause
