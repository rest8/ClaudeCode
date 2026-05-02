# Omakase Notifier — Windows installer
#
# Creates a virtualenv, installs Python dependencies and Playwright
# browsers, copies the example config if needed, and places a desktop
# shortcut named "Omakase Notifier".
#
# Usage (from a regular PowerShell, not admin):
#   cd <project root>
#   powershell -ExecutionPolicy Bypass -File scripts\install_windows.ps1
#
# Re-run safely: it is idempotent.

param(
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"

$root = Resolve-Path "$PSScriptRoot\.."
Set-Location $root

Write-Host "[omakase] project root: $root"

# 1. virtualenv
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "[omakase] creating virtualenv..."
    & $Python -m venv .venv
}

$pip = ".\.venv\Scripts\pip.exe"
$py  = ".\.venv\Scripts\python.exe"

Write-Host "[omakase] upgrading pip..."
& $py -m pip install --upgrade pip | Out-Host

Write-Host "[omakase] installing requirements..."
& $pip install -r requirements.txt | Out-Host

Write-Host "[omakase] installing Playwright Chromium..."
& $py -m playwright install chromium | Out-Host

# 2. config.yaml
if (-not (Test-Path "config.yaml")) {
    Copy-Item "config.example.yaml" "config.yaml"
    Write-Host "[omakase] config.yaml created from template — edit it before first run."
}

# 3. data dir
New-Item -ItemType Directory -Force -Path "data" | Out-Null

# 4. desktop shortcut (also auto-created on first app launch via bootstrap.py)
$desktop = [Environment]::GetFolderPath("Desktop")
$shortcutPath = Join-Path $desktop "Omakase Notifier.lnk"
$pyw = Join-Path $root ".venv\Scripts\pythonw.exe"
$launcher = Join-Path $root "launcher.py"

$wshell = New-Object -ComObject WScript.Shell
$shortcut = $wshell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $pyw
$shortcut.Arguments = "`"$launcher`""
$shortcut.WorkingDirectory = $root

$iconPath = Join-Path $root "assets\icon.ico"
if (Test-Path $iconPath) {
    $shortcut.IconLocation = "$iconPath,0"
} else {
    $shortcut.IconLocation = "$pyw,0"
}
$shortcut.Save()

Write-Host "[omakase] desktop shortcut created: $shortcutPath"
Write-Host "[omakase] done. Edit config.yaml then double-click the desktop icon."
