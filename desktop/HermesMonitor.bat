@echo off
REM Hermes Monitor (Windows) - double-click to launch
setlocal
set "APP_DIR=__APP_DIR__"
if "%APP_DIR%"=="__APP_DIR__" set "APP_DIR=%~dp0"

cd /d "%APP_DIR%"

if exist ".env" (
  for /f "usebackq tokens=1,* delims==" %%A in (".env") do (
    if not "%%A"=="" if not "%%A:~0,1%"=="#" set "%%A=%%B"
  )
)

if exist ".venv\Scripts\python.exe" (
  set "PYTHON=.venv\Scripts\python.exe"
) else (
  set "PYTHON=python"
)

echo ================================================================
echo   Hermes Stock Monitor
echo   %date% %time%
echo ================================================================
"%PYTHON%" "%APP_DIR%\hermes_monitor.py" %*
pause
