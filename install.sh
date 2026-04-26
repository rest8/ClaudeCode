#!/usr/bin/env bash
# ============================================================
#  Hermes Monitor インストーラ
#   - venv 作成 + 依存インストール
#   - デスクトップにダブルクリック起動アイコンを配置
#   - 任意で systemd / launchd サービス登録
# ============================================================
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"

OS="$(uname)"
DESKTOP_DIR="${XDG_DESKTOP_DIR:-$HOME/Desktop}"
[ -d "$DESKTOP_DIR" ] || DESKTOP_DIR="$HOME/Desktop"
mkdir -p "$DESKTOP_DIR"

echo ">>> 1/4: Python venv を作成"
if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
./.venv/bin/pip install --quiet --upgrade pip
./.venv/bin/pip install --quiet -r requirements.txt
echo "    OK"

echo ">>> 2/4: run.sh を実行可能に"
chmod +x run.sh
echo "    OK"

echo ">>> 3/4: デスクトップアイコンを配置 ($OS)"
case "$OS" in
  Linux)
    sed "s|__APP_DIR__|$HERE|g" \
      "$HERE/desktop/HermesMonitor.desktop.in" \
      > "$DESKTOP_DIR/HermesMonitor.desktop"
    chmod +x "$DESKTOP_DIR/HermesMonitor.desktop"
    # GNOME (3.36+) では trust 属性を立てないと double-click できない
    if command -v gio >/dev/null 2>&1; then
      gio set "$DESKTOP_DIR/HermesMonitor.desktop" "metadata::trusted" true || true
    fi
    echo "    -> $DESKTOP_DIR/HermesMonitor.desktop"
    ;;
  Darwin)
    sed "s|__APP_DIR__|$HERE|g" \
      "$HERE/desktop/HermesMonitor.command" \
      > "$DESKTOP_DIR/HermesMonitor.command"
    chmod +x "$DESKTOP_DIR/HermesMonitor.command"
    # アイコンを設定 (Finder 用)
    if command -v sips >/dev/null 2>&1 && command -v Rez >/dev/null 2>&1; then
      ICN_PNG="$HERE/assets/hermes-icon.png"
      if [ ! -f "$ICN_PNG" ] && command -v rsvg-convert >/dev/null 2>&1; then
        rsvg-convert "$HERE/assets/hermes-icon.svg" -w 512 -h 512 -o "$ICN_PNG" || true
      fi
    fi
    echo "    -> $DESKTOP_DIR/HermesMonitor.command"
    ;;
  *)
    # Windows (Git Bash / MSYS / Cygwin) の場合
    sed "s|__APP_DIR__|$(cygpath -w "$HERE" 2>/dev/null || echo "$HERE")|g" \
      "$HERE/desktop/HermesMonitor.bat" \
      > "$DESKTOP_DIR/HermesMonitor.bat"
    echo "    -> $DESKTOP_DIR/HermesMonitor.bat"
    ;;
esac

echo ">>> 4/4: 常駐化サービス登録 (任意)"
read -r -p "    システム常駐 (バックグラウンド自動起動) しますか? [y/N]: " yn || yn=""
case "$yn" in
  [Yy]*)
    case "$OS" in
      Linux)
        SERVICE_DIR="$HOME/.config/systemd/user"
        mkdir -p "$SERVICE_DIR"
        sed "s|__APP_DIR__|$HERE|g" \
          "$HERE/service/hermes-monitor.service" \
          > "$SERVICE_DIR/hermes-monitor.service"
        systemctl --user daemon-reload
        systemctl --user enable --now hermes-monitor.service
        # ログイン時自動起動 (lingering)
        loginctl enable-linger "$(id -un)" 2>/dev/null || true
        echo "    systemd --user で起動しました。"
        echo "    確認: systemctl --user status hermes-monitor"
        echo "    停止: systemctl --user stop hermes-monitor"
        ;;
      Darwin)
        AGENT="$HOME/Library/LaunchAgents/com.hermes.monitor.plist"
        mkdir -p "$(dirname "$AGENT")"
        sed "s|__APP_DIR__|$HERE|g" \
          "$HERE/service/com.hermes.monitor.plist" \
          > "$AGENT"
        launchctl unload "$AGENT" 2>/dev/null || true
        launchctl load "$AGENT"
        echo "    launchd で起動しました ($AGENT)"
        echo "    停止: launchctl unload \"$AGENT\""
        ;;
      *)
        echo "    Windows では『タスクスケジューラ』に %~dp0\\desktop\\HermesMonitor.bat を登録してください。"
        ;;
    esac
    ;;
  *)
    echo "    スキップしました。デスクトップアイコンから手動起動できます。"
    ;;
esac

echo ""
echo "================================================================"
echo "  ✅ インストール完了"
echo ""
echo "  次に .env を作成してください:"
echo "      cp .env.example .env"
echo "      vi .env   # GOOGLE_CHAT_WEBHOOK / LINE_CHANNEL_TOKEN / LINE_TO を設定"
echo ""
echo "  デスクトップの『Hermes Monitor』アイコンを double-click で起動"
echo "================================================================"
