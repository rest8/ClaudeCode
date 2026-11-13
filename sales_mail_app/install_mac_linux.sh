#!/usr/bin/env bash
# ソースから使う場合: 必要なライブラリを入れ、デスクトップにアイコン（クリックでターミナルが開く）を作る
set -euo pipefail
cd "$(dirname "$0")"
python3 -m pip install --user -r requirements.txt
python3 run_app.py --install-shortcut
