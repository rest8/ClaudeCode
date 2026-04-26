#!/usr/bin/env bash
# macOS では .command ファイルを Finder で double-click すると Terminal で開く
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# install.sh が APP_DIR を埋め込む
APP_DIR="__APP_DIR__"
if [ "$APP_DIR" = "__APP_DIR__" ]; then
  APP_DIR="$HERE"
fi
exec "$APP_DIR/run.sh" "$@"
