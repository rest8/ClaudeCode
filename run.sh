#!/usr/bin/env bash
# Hermes Monitor 実行スクリプト (デスクトップアイコン / サービスから呼ばれる)

set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"

# .env があれば読み込む (GOOGLE_CHAT_WEBHOOK / LINE_CHANNEL_TOKEN / LINE_TO 等)
if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
fi

if [ -d .venv ]; then
  PYTHON="$HERE/.venv/bin/python"
else
  PYTHON="$(command -v python3 || command -v python)"
fi

echo "================================================================"
echo "  Hermes 在庫監視 起動"
echo "  $(date '+%Y-%m-%d %H:%M:%S')"
echo "  Python: $PYTHON"
echo "  Args:   $*"
echo "================================================================"

# デスクトップから double-click された場合、ターミナルを開いた状態で実行
exec "$PYTHON" "$HERE/hermes_monitor.py" "$@"
