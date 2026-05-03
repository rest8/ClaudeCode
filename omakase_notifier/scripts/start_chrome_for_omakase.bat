@echo off
REM Launch Chrome with remote debugging enabled for the Omakase
REM Notifier crawler to attach to via CDP. Keep this Chrome window
REM open while you use the app.
REM
REM After launching:
REM   1. Browse to https://omakase.in/r once and pass any Cloudflare
REM      challenge yourself (one-time).
REM   2. In config.yaml set:
REM        app:
REM          use_cdp: true
REM          cdp_url: "http://localhost:9222"
REM   3. Restart the Omakase Notifier app.
REM
REM This runs your real Chrome (not Playwright's bundled Chromium),
REM with a dedicated profile so it doesn't disturb your normal
REM browsing. Cloudflare cannot distinguish this from any other
REM real-user session.

setlocal

set "DATA_DIR=%LOCALAPPDATA%\OmakaseNotifierChrome"

set "CHROME=%ProgramFiles%\Google\Chrome\Application\chrome.exe"
if not exist "%CHROME%" set "CHROME=%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"
if not exist "%CHROME%" set "CHROME=%LocalAppData%\Google\Chrome\Application\chrome.exe"

if not exist "%CHROME%" (
    echo ERROR: chrome.exe not found in standard locations.
    echo Edit start_chrome_for_omakase.bat and set CHROME to your chrome.exe path.
    pause
    exit /b 1
)

echo Launching Chrome:  "%CHROME%"
echo Profile dir:       "%DATA_DIR%"
echo Remote debugging:  http://localhost:9222
echo.
echo Keep this Chrome window open. Pass the Cloudflare challenge once
echo in the browser, then start (or restart) the Omakase Notifier app.
echo.

start "" "%CHROME%" ^
    --remote-debugging-port=9222 ^
    --user-data-dir="%DATA_DIR%" ^
    --no-first-run ^
    --no-default-browser-check ^
    https://omakase.in/r

endlocal
