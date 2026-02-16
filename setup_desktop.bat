@echo off
chcp 65001 >nul
setlocal

set "SCRIPT_DIR=%~dp0"
set "DESKTOP=%USERPROFILE%\Desktop"
set "SHORTCUT=%DESKTOP%\Market Dashboard.lnk"
set "VBS_TEMP=%TEMP%\create_shortcut.vbs"

echo Set ws = CreateObject("WScript.Shell") > "%VBS_TEMP%"
echo Set sc = ws.CreateShortcut("%SHORTCUT%") >> "%VBS_TEMP%"
echo sc.TargetPath = "%SCRIPT_DIR%launch_dashboard.bat" >> "%VBS_TEMP%"
echo sc.WorkingDirectory = "%SCRIPT_DIR%" >> "%VBS_TEMP%"
echo sc.IconLocation = "%SCRIPT_DIR%market_dashboard.ico" >> "%VBS_TEMP%"
echo sc.WindowStyle = 7 >> "%VBS_TEMP%"
echo sc.Description = "Market Data Dashboard" >> "%VBS_TEMP%"
echo sc.Save >> "%VBS_TEMP%"

cscript //nologo "%VBS_TEMP%"
del "%VBS_TEMP%"

echo.
echo デスクトップにショートカットを作成しました: %SHORTCUT%
echo ダブルクリックで Market Dashboard を起動できます。
pause
