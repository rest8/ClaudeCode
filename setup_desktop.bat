@echo off
chcp 65001 >nul 2>nul
setlocal enabledelayedexpansion

set "SCRIPT_DIR=%~dp0"
set "DESKTOP=%USERPROFILE%\Desktop"
set "VBS_TEMP=%TEMP%\create_shortcut.vbs"

> "%VBS_TEMP%" (
    echo Dim ws, sc, desktop, scriptDir
    echo Set ws = CreateObject^("WScript.Shell"^)
    echo scriptDir = ws.ExpandEnvironmentStrings^("!SCRIPT_DIR!"^)
    echo desktop = ws.ExpandEnvironmentStrings^("!DESKTOP!"^)
    echo Set sc = ws.CreateShortcut^(desktop ^& "\Market Dashboard.lnk"^)
    echo sc.TargetPath = scriptDir ^& "launch_dashboard.bat"
    echo sc.WorkingDirectory = scriptDir
    echo sc.IconLocation = scriptDir ^& "market_dashboard.ico"
    echo sc.WindowStyle = 7
    echo sc.Description = "Market Data Dashboard"
    echo sc.Save
)

cscript //nologo "%VBS_TEMP%"
set "RESULT=%ERRORLEVEL%"
del "%VBS_TEMP%" 2>nul

echo.
if %RESULT% equ 0 (
    echo Done: %DESKTOP%\Market Dashboard.lnk
) else (
    echo Error: Failed to create shortcut.
)
pause
