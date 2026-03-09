# Omakase Auto-Booker

Omakase（omakase.in）の飲食店予約を自動化するPythonプログラムです。
Google カレンダーの空きスケジュールを確認し、対象レストランの予約枠が開いたタイミングで自動予約を行います。

## 仕組み

1. **Google カレンダー連携**: 指定期間のカレンダーをチェックし、食事に使える空き時間を特定
2. **Omakase 自動操作**: Playwright（ブラウザ自動化）で omakase.in にログインし、空き枠を監視
3. **自動予約**: カレンダーの空き時間と Omakase の空き枠が一致したら即座に予約を確保
4. **予約開始時刻の高速ポーリング**: 予約開始時刻（デフォルト10:00 JST）前後は5秒間隔で監視

## セットアップ

### 1. 依存パッケージのインストール

```bash
pip install -r requirements.txt
playwright install chromium
```

### 2. Google Calendar API の設定

1. [Google Cloud Console](https://console.cloud.google.com/) でプロジェクトを作成
2. Google Calendar API を有効化
3. OAuth 2.0 クライアント ID を作成（デスクトップアプリ）
4. `credentials.json` をプロジェクトルートにダウンロード

### 3. 設定ファイルの作成

```bash
cp config.example.yaml config.yaml
```

`config.yaml` を編集し、以下を設定:
- Omakase のメールアドレス・パスワード
- 予約したいレストランのURL・人数・希望時間
- ポーリング間隔などのオプション

### 4. 実行

```bash
python -m omakase_booker
```

初回実行時にブラウザが開き、Google アカウントの認証を求められます。

## 設定例

```yaml
target_restaurants:
  - name: "鮨 さいとう"
    omakase_url: "https://omakase.in/r/example123"
    party_size: 2
    preferred_times:
      - "18:00"
      - "19:00"
```

## 注意事項

- `config.yaml`, `credentials.json`, `token.json` は `.gitignore` に含まれており、コミットされません
- `headless: false` に設定するとブラウザの動作を目視確認できます（デバッグ用）
- Omakase のUI変更により動作しなくなる場合があります。その場合は `omakase_client.py` のセレクタを調整してください
