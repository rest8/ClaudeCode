# Removes the desktop shortcut. Does not delete data/ or config.yaml.

$desktop = [Environment]::GetFolderPath("Desktop")
$shortcutPath = Join-Path $desktop "Omakase Notifier.lnk"
if (Test-Path $shortcutPath) {
    Remove-Item $shortcutPath -Force
    Write-Host "[omakase] removed $shortcutPath"
} else {
    Write-Host "[omakase] no shortcut to remove."
}
