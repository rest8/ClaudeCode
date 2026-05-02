@echo off
REM Omakase 空席通知アプリ - Windows 起動バッチ
setlocal

set SCRIPT_DIR=%~dp0
cd /d "%SCRIPT_DIR%"

if not exist .venv (
    echo [SETUP] 仮想環境を作成します...
    python -m venv .venv
    if errorlevel 1 (
        echo [ERROR] 仮想環境の作成に失敗しました。Python 3.10-3.14 がインストールされ PATH に追加されているか確認してください。
        exit /b 1
    )
    call .venv\Scripts\activate.bat
    python -m pip install --upgrade pip
    pip install -r requirements.txt
    if errorlevel 1 (
        echo [ERROR] 依存パッケージのインストールに失敗しました。
        exit /b 1
    )
) else (
    call .venv\Scripts\activate.bat
)

if not exist config.yaml (
    echo [ERROR] config.yaml が見つかりません。config.example.yaml をコピーして編集してください。
    exit /b 1
)

python -m omakase_notifier --config config.yaml %*

endlocal
