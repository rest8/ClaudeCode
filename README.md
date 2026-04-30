# Omakase 空席通知アプリ

[Omakase](https://omakase.in/) の店舗予約ページを定期的にチェックし、
**空席が出た瞬間にメール / LINE / Webhook へ通知** する Windows 常駐アプリです。

## 特長

- システムトレイに常駐（pystray）
- 監視対象店舗・日付・時間帯・人数を YAML で柔軟に設定
- メール（SMTP）/ LINE Messaging API / 任意 Webhook の複数チャネル併用可
- 状態保存により「新規に空いた枠」のみを通知（スパム防止）
- ローテーティングログ出力

## セットアップ (Windows)

1. [Python 3.10+](https://www.python.org/downloads/) をインストール（PATH に追加）
2. このリポジトリを取得し、`config.example.yaml` を `config.yaml` にコピーして編集
3. `run.bat` をダブルクリック（初回は仮想環境を作成し依存パッケージを導入）

```cmd
copy config.example.yaml config.yaml
notepad config.yaml
run.bat
```

### スタートアップ登録（自動起動）

Win + R で `shell:startup` を開き、`run.bat` のショートカットを配置してください。
PC ログイン時に自動的に常駐起動します。

## 設定例（抜粋）

```yaml
targets:
  - name: "○○寿司 銀座"
    url: "https://omakase.in/ja/r/xxxxxxxx"
    dates: ["2026-05-15", "2026-05-22"]
    party_size: 2

poll_interval_seconds: 90

cookies:
  _omakase_session: "ブラウザからコピー"

notifications:
  email:
    enabled: true
    smtp_host: smtp.gmail.com
    smtp_port: 587
    use_tls: true
    username: you@gmail.com
    password: "Gmail アプリパスワード"
    from_addr: you@gmail.com
    to_addrs: [you@gmail.com]

  line:
    enabled: true
    channel_access_token: "LINE Developers のチャネルアクセストークン"
    to: "通知先ユーザID または グループID"
```

### LINE 通知の準備

`LINE Notify` は終了済みのため、本アプリは **LINE Messaging API** を使用します。

1. <https://developers.line.biz/console/> でプロバイダ / Messaging API チャネルを作成
2. 長期チャネルアクセストークンを発行し `channel_access_token` に貼り付け
3. ボットを友だち追加し、`to` に自分のユーザID（または通知したいグループID）を指定
   - ユーザIDは Webhook を有効化して受信イベントから確認できます

### 認証 Cookie の取得

Omakase の店舗ページは未ログインで空席が見える場合もありますが、
ログイン必須ページを監視する場合は次の手順で Cookie を取得します。

1. ブラウザで Omakase にログイン
2. F12 → Application → Cookies → `https://omakase.in`
3. 必要な Cookie（例: `_omakase_session`）を `cookies:` に列挙

## 使い方

```cmd
REM 通常起動（トレイ常駐）
run.bat

REM トレイなしでフォアグラウンド実行
python -m omakase_notifier --config config.yaml --no-tray

REM 1回だけチェック（疎通テスト用）
python -m omakase_notifier --config config.yaml --once
```

トレイアイコン右クリックで「今すぐチェック」「終了」が選べます。

## ファイル構成

```
omakase_notifier/
  __main__.py        エントリポイント
  app.py             ポーリングループ
  config.py          YAML 設定ロード
  scraper.py         Omakase HTML 解析
  notifier.py        メール / LINE / Webhook 送信
  state.py           前回検知状態の永続化
  tray.py            システムトレイ
  logging_setup.py   ログ設定
config.example.yaml  設定テンプレート
requirements.txt     依存パッケージ
run.bat              Windows 起動ヘルパー
```

## 動作の仕組み

1. `poll_interval_seconds` 間隔で各 `target` の URL を HTTP GET
2. 取得 HTML から JSON-LD / `data-*` 属性 / カレンダーセルを横断的に解析し空席候補を抽出
3. 設定に応じて日付・時間帯・人数でフィルタ
4. `state.json` に保存された前回スナップショットと比較し、**新規に出現した枠** のみを通知
5. 通知後にスナップショットを更新

## 留意事項

- **過度なポーリングは避けてください**。既定の 90 秒以上を推奨します。
  サイトに負荷をかけたり、利用規約違反となる恐れがあります。
- Omakase のページ構造は予告なく変わる可能性があります。空席が検知できない場合は
  `omakase_notifier/scraper.py` のセレクタ／キーワードを調整してください。
- 本アプリは個人利用を想定しています。商用・転売目的での使用はお控えください。
- `config.yaml` には認証情報が含まれます。Git にコミットしないでください。
