#!/usr/bin/env bash
# SalesMailer（ターミナル版の実行ファイル）を作成する（macOS）。python.org 版の Python 3.10 以上を推奨。
set -euo pipefail
cd "$(dirname "$0")"
[ -d .venv ] || python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements-dev.txt
pyinstaller --noconfirm --onefile --console --name SalesMailer --icon assets/icon.ico --add-data assets:assets \
  --collect-submodules anthropic --collect-submodules textual --collect-data textual --collect-submodules rich run_app.py
echo "完成: dist/SalesMailer"
echo "デスクトップにアイコンを作るには: ./dist/SalesMailer --install-shortcut"
