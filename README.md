# Omakase 空席通知アプリ

[Omakase](https://omakase.in/) の店舗予約ページを定期的にチェックし、
**空席が出た瞬間にメール / LINE / Webhook へ通知** する Windows 常駐アプリです。

**配信先（メールアドレス・LINE 宛先）ごとに** 監視したい店舗・日付・人数を
個別に設定できます。

## 特長

- システムトレイ常駐（pystray）
- **店舗一覧の自動クロール** — Omakase 掲載店をリストアップしキャッシュ
- **配信先ごとの購読管理** — メール/LINE/Webhook を任意の数だけ登録、各配信先が監視する店舗を個別選択
- 状態保存により「新規に空いた枠」のみを通知（スパム防止）
- 配信先 × 店舗 単位で重複通知を防止
- ローテーティングログ出力
- Python 3.10〜3.14 対応

## セットアップ (Windows)

1. [Python 3.10〜3.14](https://www.python.org/downloads/) をインストール（PATH に追加）。Python 3.14.4 で動作確認済み
2. このリポジトリを取得
3. 設定ファイルを作成して認証情報を記入
4. **店舗一覧をクロール → 配信先を追加 → 店舗を購読 → 監視開始**

```cmd
copy config.example.yaml config.yaml
notepad config.yaml

REM 初回セットアップ (依存インストール) は run.bat または手動で:
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## 使い方（CLI）

すべて `python -m omakase_notifier <subcommand>` で実行します。
（仮想環境を有効化した状態で）

### 1. 店舗一覧をクロール

```cmd
python -m omakase_notifier discover
```

`https://omakase.in/ja/restaurants` を起点に巡回し、`restaurants.json` に
キャッシュします。`--url` で起点URLを追加指定可能。

### 2. 店舗を検索

```cmd
python -m omakase_notifier restaurants --search "銀座"
python -m omakase_notifier restaurants --limit 50
```

`<restaurant_id>` をメモしておきます。

### 3. 配信先を追加

```cmd
REM メール宛先
python -m omakase_notifier add-subscriber --id alice --channel email --to alice@example.com --label "Alice"

REM LINE 宛先 (userId は LINE Messaging API の Webhook で取得)
python -m omakase_notifier add-subscriber --id bob --channel line --to U1234567890abcdef --label "Bob"

REM Webhook (Slack/Discord/ntfy.sh など任意)
python -m omakase_notifier add-subscriber --id team --channel webhook --to https://hooks.slack.com/...
```

### 4. 配信先ごとに店舗を購読

```cmd
python -m omakase_notifier subscribe alice abc123 --date 2026-05-15 --date 2026-05-22 --party-size 2
python -m omakase_notifier subscribe bob   abc123 --time 19:00 --time 19:30 --party-size 4
python -m omakase_notifier subscribe alice def456
```

引数:
- `--date YYYY-MM-DD` (複数可) … 監視日。省略で任意の日付
- `--time HH:MM` (複数可) … 監視時刻。省略で任意の時刻
- `--party-size N` … 必要な人数（その人数以上の空席のみ通知）

### 5. 一覧確認

```cmd
python -m omakase_notifier subscribers
```

```
[alice] (Alice)  email -> alice@example.com
    監視店舗:
      - abc123  ○○寿司 銀座  [日付=2026-05-15,2026-05-22, 人数>=2]
      - def456  △△焼鳥
[bob] (Bob)  line -> U1234567890abcdef
    監視店舗:
      - abc123  ○○寿司 銀座  [時間=19:00,19:30, 人数>=4]
```

### 6. 購読解除・配信先削除

```cmd
python -m omakase_notifier unsubscribe alice abc123
python -m omakase_notifier remove-subscriber --id alice
```

### 7. 監視開始

```cmd
REM トレイ常駐（既定）
python -m omakase_notifier
REM または
python -m omakase_notifier run

REM 1回だけチェック (動作確認用)
python -m omakase_notifier --once

REM トレイなし (フォアグラウンド)
python -m omakase_notifier --no-tray
```

または **`run.bat` をダブルクリック** で起動（依存導入も自動）。

## 動作の仕組み

1. `subscribers.yaml` の購読を集計し、誰かが監視している店舗の集合を作る
2. `poll_interval_seconds` 間隔で各店舗のページを取得（同じ店舗は1回だけ）
3. 取得した空席候補を、配信先の購読条件（日付・時刻・人数）でフィルタ
4. `state.json` の (配信先 × 店舗) 単位スナップショットと比較
5. **新規に出現した枠のみ** を該当配信先へ送信、状態を更新

## ファイル構成

```
omakase_notifier/
  __main__.py        エントリポイント (CLI)
  cli.py             サブコマンド実装
  app.py             ポーリングループ
  config.py          config.yaml ロード
  restaurants.py     店舗一覧クロール / キャッシュ
  subscribers.py     subscribers.yaml CRUD
  scraper.py         空席判定 (HTML解析)
  notifier.py        メール/LINE/Webhook 送信
  state.py           (配信先×店舗) 状態保存
  tray.py            システムトレイ
  logging_setup.py   ログ設定
config.example.yaml      共通設定テンプレート
subscribers.example.yaml 配信先ファイル形式の例
requirements.txt
run.bat
```

## LINE 通知の準備

`LINE Notify` は終了済みのため、本アプリは **LINE Messaging API** を使用します。

1. <https://developers.line.biz/console/> でプロバイダ / Messaging API チャネルを作成
2. **長期チャネルアクセストークン** を発行 → `config.yaml` の `notifications.line.channel_access_token` に貼り付け
3. ボットを友だち追加し、自分の **userId** を取得（Webhook 受信イベントから確認）
4. `add-subscriber --channel line --to <userId>` で配信先登録

## 認証 Cookie の取得

Omakase の店舗一覧や予約カレンダーがログイン必須の場合：

1. ブラウザで Omakase にログイン
2. F12 → Application → Cookies → `https://omakase.in`
3. 必要な Cookie を `config.yaml` の `cookies:` に列挙

## スタートアップ登録（自動起動）

`Win + R` → `shell:startup` → 開いたフォルダに `run.bat` のショートカットを配置。
PCログイン時に常駐起動します。

## 留意事項

- **過度なポーリングは避けてください。** 既定の 90 秒以上を推奨します。
- Omakase のページ構造は予告なく変わる可能性があります。空席や店舗一覧が
  抽出できない場合は `restaurants.py` / `scraper.py` のセレクタを調整してください。
- 本アプリは個人利用を想定しています。商用・転売目的での使用はお控えください。
- `config.yaml` / `subscribers.yaml` には認証情報や個人宛先が含まれます。Git に
  コミットしないでください（`.gitignore` 済み）。
