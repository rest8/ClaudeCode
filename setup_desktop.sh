#!/bin/bash
# デスクトップにショートカットを配置するセットアップスクリプト
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DESKTOP_DIR="${XDG_DESKTOP_DIR:-$HOME/Desktop}"
DESKTOP_FILE="$DESKTOP_DIR/MarketDashboard.desktop"

# デスクトップディレクトリがなければ作成
mkdir -p "$DESKTOP_DIR"

# .desktop ファイルを生成（パスを実際の場所に合わせる）
cat > "$DESKTOP_FILE" <<EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=Market Dashboard
Comment=Market Data Dashboard - 為替・株価・プラチナ先物
Exec=bash -c 'cd "$SCRIPT_DIR" && python3 market_dashboard.py'
Icon=$SCRIPT_DIR/market_dashboard.svg
Path=$SCRIPT_DIR
Terminal=false
Categories=Finance;Utility;
StartupNotify=false
EOF

chmod +x "$DESKTOP_FILE"

# GNOME環境の場合、信頼済みに設定
if command -v gio &>/dev/null; then
    gio set "$DESKTOP_FILE" metadata::trusted true 2>/dev/null || true
fi

echo "デスクトップにショートカットを作成しました: $DESKTOP_FILE"
echo "ダブルクリックで Market Dashboard を起動できます。"
