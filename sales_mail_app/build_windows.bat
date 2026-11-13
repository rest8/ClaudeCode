@echo off
rem Build SalesMailer.exe (Windows). Requires Python 3.10+ from python.org.
cd /d %~dp0
if not exist .venv py -3 -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements-dev.txt
pyinstaller --noconfirm --onefile --console --name SalesMailer --icon assets\icon.ico --add-data "assets;assets" --collect-submodules anthropic --collect-submodules textual --collect-data textual --collect-submodules rich run_app.py
echo.
echo Done: dist\SalesMailer.exe
echo Run "dist\SalesMailer.exe --install-shortcut" to put an icon on your Desktop.
pause
