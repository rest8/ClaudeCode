# Hermes 在庫監視 → Google Chat / LINE 通知

Hermes オンラインを定期巡回し、以下 6 種の入荷を **Google Chat** と **LINE** にリンク付きでリアルタイム通知します。

| # | 監視対象 | 検索キー |
|---|---------|----------|
| 1 | ケリー       | kelly      |
| 2 | バーキン     | birkin     |
| 3 | ピコタン     | picotin    |
| 4 | コンスタンス | constance  |
| 5 | エヴリン     | evelyne    |
| 6 | アッカド     | akkad      |

## 主な機能

- **強化されたアンチBot対策**: `curl_cffi` で Chrome の TLS/JA3 を完全模倣 (Akamai Bot Manager 突破に有効) → 失敗時 `cloudscraper` → `requests` に自動フォールバック
- **ジッタ + プロキシローテーション**: 等間隔リクエストを避け、複数プロキシを順番に使用
- **マルチ通知**: Google Chat / LINE Messaging API に同時送信
- **常駐化**: systemd (Linux) / launchd (macOS) / タスクスケジューラ (Windows)
- **デスクトップアイコン**: ダブルクリックで即起動

## クイックスタート

```bash
# 1. インストール (venv 作成 + 依存導入 + デスクトップアイコン配置)
bash install.sh

# 2. 環境変数を設定
cp .env.example .env
$EDITOR .env   # Webhook / LINE Token を埋める

# 3. デスクトップの『Hermes Monitor』アイコンを double-click 🎉
```

## 通知先の取得方法

### Google Chat
1. 通知したいスペースを開く
2. スペース名 → **設定 → アプリと統合 → Webhook を追加**
3. URL を `.env` の `GOOGLE_CHAT_WEBHOOK` に設定

### LINE (Messaging API)
LINE Notify は 2025年4月で終了したため、Messaging API を使用します。

1. <https://developers.line.biz/console/> で **Provider → Messaging API channel** を作成
2. **Messaging API 設定** から「Channel access token (long-lived)」を発行 → `.env` の `LINE_CHANNEL_TOKEN`
3. 作成した Bot を友達追加 / グループに招待
4. 宛先 ID を取得 (Webhook event の `source.userId` / `groupId` / `roomId`) → `.env` の `LINE_TO`
   - 開発時は <https://developers.line.biz/console/> の "Your user ID" でも可
5. (任意) Bot のあいさつメッセージ・自動応答はオフにすると静か

## 常駐化 (バックグラウンド自動起動)

`install.sh` の対話で `y` を選ぶと自動で登録します。手動でやる場合:

### Linux (systemd --user)
```bash
sed "s|__APP_DIR__|$(pwd)|g" service/hermes-monitor.service \
  > ~/.config/systemd/user/hermes-monitor.service
systemctl --user daemon-reload
systemctl --user enable --now hermes-monitor
loginctl enable-linger "$(id -un)"   # ログアウト後も走らせる
journalctl --user -u hermes-monitor -f   # ログ確認
```

### macOS (launchd)
```bash
sed "s|__APP_DIR__|$(pwd)|g" service/com.hermes.monitor.plist \
  > ~/Library/LaunchAgents/com.hermes.monitor.plist
launchctl load ~/Library/LaunchAgents/com.hermes.monitor.plist
tail -f hermes-monitor.log
```

### Windows
タスクスケジューラで「ログオン時にトリガー」、操作に `desktop/HermesMonitor.bat` を指定。

## デスクトップアイコン

`install.sh` がOSを検出し、以下を `~/Desktop` に配置:

| OS | ファイル | 動作 |
|----|---------|------|
| Linux | `HermesMonitor.desktop` | ターミナル付きで起動 |
| macOS | `HermesMonitor.command`  | Terminal.app で起動 |
| Windows | `HermesMonitor.bat`     | コマンドプロンプトで起動 |

アイコン画像は `assets/hermes-icon.svg`。

## アンチBot対策の詳細

| 対策 | 実装 |
|------|------|
| TLS/JA3 フィンガープリント | `curl_cffi` で Chrome 124 を完全模倣 |
| User-Agent ローテーション  | Chrome / Safari / Firefox の最新 4 種 |
| ヘッダの自然さ            | `sec-ch-ua` / `Accept-Language` / `Referer` を本物同等 |
| Cookie 永続化              | セッション内で `bm_sz` 等を保持 |
| Warmup                     | 初回にトップページを叩いてセッション温める |
| ジッタ                     | 巡回間隔に ±30% 揺らぎ (`HERMES_JITTER`) |
| プロキシローテーション     | `HERMES_PROXIES=p1,p2,...` で順番に使用 |
| HTML フォールバック        | API がブロックされたら `__NEXT_DATA__` をパース |

## CLI

```bash
python3 hermes_monitor.py --interval 30 --locale jp/ja
python3 hermes_monitor.py --webhook https://... --line-token XXX --line-to U...
```

## テスト

```bash
.venv/bin/pip install pytest
.venv/bin/pytest test_hermes_monitor.py -v
```

14 件のテスト (抽出 / 通知 / クールダウン / マルチ通知) がネットワーク無しで実行されます。

## ⚠ 重要な注意

- **`HERMES_INTERVAL=1` (1秒間隔) は Hermes 利用規約違反の可能性が高く、IPブロック・法的リスクがあります**。Hermes は Akamai Bot Manager を導入しています。
- 推奨は `30〜60` 秒。アンチBot対策を強化していますが、絶対の保証はできません。
- 個人利用の範囲内で、自己責任にてご利用ください。

## ファイル構成

```
ClaudeCode/
├── hermes_monitor.py        # 監視ループ
├── http_client.py           # アンチBot HTTP
├── notifiers.py             # Google Chat / LINE 通知
├── test_hermes_monitor.py   # 14 tests
├── requirements.txt
├── run.sh                   # ランチャ (デスクトップから呼ぶ)
├── install.sh               # 一括インストーラ
├── .env.example
├── assets/hermes-icon.svg   # アプリアイコン
├── desktop/                 # デスクトップ用ランチャ雛形
│   ├── HermesMonitor.desktop.in   # Linux
│   ├── HermesMonitor.command      # macOS
│   └── HermesMonitor.bat          # Windows
└── service/                 # 常駐化用ユニット
    ├── hermes-monitor.service     # systemd
    └── com.hermes.monitor.plist   # launchd
```
