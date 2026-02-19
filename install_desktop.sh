#!/bin/bash
# Install World Monitor desktop shortcut
# Usage: ./install_desktop.sh

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DESKTOP_FILE="$SCRIPT_DIR/world-monitor.desktop"

# Update paths in .desktop file to match actual install location
sed -i "s|Exec=.*|Exec=bash -c 'cd $SCRIPT_DIR \&\& ./launch.sh'|" "$DESKTOP_FILE"
sed -i "s|Icon=.*|Icon=$SCRIPT_DIR/static/icon.svg|" "$DESKTOP_FILE"

# Detect Desktop directory
DESKTOP_DIR=""
if command -v xdg-user-dir &>/dev/null; then
    DESKTOP_DIR="$(xdg-user-dir DESKTOP 2>/dev/null)"
fi
if [ -z "$DESKTOP_DIR" ] || [ ! -d "$DESKTOP_DIR" ]; then
    if [ -d "$HOME/Desktop" ]; then
        DESKTOP_DIR="$HOME/Desktop"
    elif [ -d "$HOME/デスクトップ" ]; then
        DESKTOP_DIR="$HOME/デスクトップ"
    else
        DESKTOP_DIR="$HOME/Desktop"
        mkdir -p "$DESKTOP_DIR"
    fi
fi

# Copy to Desktop
cp "$DESKTOP_FILE" "$DESKTOP_DIR/world-monitor.desktop"
chmod +x "$DESKTOP_DIR/world-monitor.desktop"

# Also install to system applications menu (if writable)
APP_DIR="$HOME/.local/share/applications"
mkdir -p "$APP_DIR"
cp "$DESKTOP_FILE" "$APP_DIR/world-monitor.desktop"

# Trust the desktop file (GNOME)
if command -v gio &>/dev/null; then
    gio set "$DESKTOP_DIR/world-monitor.desktop" metadata::trusted true 2>/dev/null
fi

echo "World Monitor desktop shortcut installed!"
echo "  Desktop: $DESKTOP_DIR/world-monitor.desktop"
echo "  App menu: $APP_DIR/world-monitor.desktop"
echo ""
echo "If the icon doesn't appear, right-click the file on the Desktop"
echo "and select 'Allow Launching' or 'Trust and Launch'."
