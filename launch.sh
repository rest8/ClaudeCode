#!/bin/bash
# World Monitor Launcher
# Starts the Flask server and opens the dashboard in the default browser.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PORT="${WM_PORT:-5000}"
URL="http://localhost:${PORT}"

cd "$SCRIPT_DIR"

# Check Python
PYTHON=""
for cmd in python3 python; do
    if command -v "$cmd" &>/dev/null; then
        PYTHON="$cmd"
        break
    fi
done

if [ -z "$PYTHON" ]; then
    if command -v notify-send &>/dev/null; then
        notify-send "World Monitor" "Python が見つかりません。Python 3 をインストールしてください。" --icon=dialog-error
    fi
    echo "Error: Python not found. Please install Python 3."
    exit 1
fi

# Check dependencies
if ! "$PYTHON" -c "import flask" 2>/dev/null; then
    # Try auto-install
    echo "Installing dependencies..."
    "$PYTHON" -m pip install -r "$SCRIPT_DIR/requirements.txt" --quiet
    if [ $? -ne 0 ]; then
        if command -v notify-send &>/dev/null; then
            notify-send "World Monitor" "依存関係のインストールに失敗しました。\npip install -r requirements.txt を実行してください。" --icon=dialog-error
        fi
        echo "Error: Failed to install dependencies. Run: pip install -r requirements.txt"
        exit 1
    fi
fi

# Kill existing instance on same port
if command -v lsof &>/dev/null; then
    existing_pid=$(lsof -ti ":${PORT}" 2>/dev/null)
    if [ -n "$existing_pid" ]; then
        kill "$existing_pid" 2>/dev/null
        sleep 1
    fi
fi

# Start Flask server in background
"$PYTHON" "$SCRIPT_DIR/app.py" &
SERVER_PID=$!

# Wait for server to start
echo "Starting World Monitor..."
for i in $(seq 1 20); do
    if curl -s "$URL/api/status" &>/dev/null; then
        break
    fi
    sleep 0.5
done

# Open browser
if command -v xdg-open &>/dev/null; then
    xdg-open "$URL" 2>/dev/null
elif command -v open &>/dev/null; then
    open "$URL"
elif command -v sensible-browser &>/dev/null; then
    sensible-browser "$URL" 2>/dev/null
elif command -v firefox &>/dev/null; then
    firefox "$URL" &
elif command -v chromium-browser &>/dev/null; then
    chromium-browser "$URL" &
elif command -v google-chrome &>/dev/null; then
    google-chrome "$URL" &
fi

echo "World Monitor running at $URL (PID: $SERVER_PID)"
echo "Press Ctrl+C to stop."

# Wait for server process
wait $SERVER_PID
