@echo off
REM Omakase 空席通知アプリ - Windows 起動バッチ
setlocal

set SCRIPT_DIR=%~dp0
cd /d "%SCRIPT_DIR%"

if not exist .venv (
    echo [SETUP] 仮想環境を作成します...
    python -m venv .venv
    call .venv\Scripts\activate.bat
    pip install --upgrade pip
    pip install -r requirements.txt
) else (
    call .venv\Scripts\activate.bat
)

if not exist config.yaml (
    echo [ERROR] config.yaml が見つかりません。config.example.yaml をコピーして編集してください。
    exit /b 1
)

python -m omakase_notifier --config config.yaml %*

endlocal
