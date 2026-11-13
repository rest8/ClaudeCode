@echo off
rem Run from source: install libraries and create a Desktop icon that opens the terminal app.
cd /d %~dp0
py -3 -m pip install -r requirements.txt
py -3 run_app.py --install-shortcut
pause
