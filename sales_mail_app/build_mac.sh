#!/usr/bin/env bash
# SalesMailer.app を作成する（macOS）。python.org 版の Python 3.10 以上を推奨（Tkinter 同梱）。
set -euo pipefail
cd "$(dirname "$0")"
[ -d .venv ] || python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements-dev.txt
pyinstaller --noconfirm --windowed --name SalesMailer --collect-submodules anthropic run_app.py
echo "完成: dist/SalesMailer.app"
