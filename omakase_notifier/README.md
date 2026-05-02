# Omakase Notifier

[omakase.in](https://omakase.in/) に常駐し、登録した店舗で **空席が出た瞬間**
に、ユーザーごとに登録されたメール / LINE 宛で通知を送る Windows 向け常駐
アプリです。

> ⚠️ **必ずお読みください — 法的・倫理的な前提**
>
> Omakase の利用規約では多くの場合、自動取得（スクレイピング）が禁止または
> 制限されています。**本ソフトウェアの利用にあたっては、運営元との合意・
> 自身のアカウント範囲内での使用・低頻度アクセスなど、規約と関連法令を
> 遵守してください。** 高頻度ポーリングは相手サーバへの負荷となり、
> 不正アクセス禁止法・偽計業務妨害などのリスクを伴います。

---

## 機能概要

| 機能                            | 説明                                                          |
| ------------------------------- | ------------------------------------------------------------- |
| 掲載店リストの取得（毎日）      | `list_refresh_time`（デフォルト 04:00）に Omakase の掲載店一覧を再取得し DB 更新 |
| 空席ポーリング                  | 登録された全店舗を `poll_interval_seconds` 間隔で巡回（既定 300s） |
| 立ち上がり検知                  | 「直前は不空 → 今回開いた」スロットだけを通知（同一スロットの連投防止）  |
| メール通知                      | SMTP で送信（Gmail のアプリパスワード等）                     |
| LINE 通知                       | LINE Messaging API（公式アカウント＋友だち追加が必要）       |
| 管理者ターミナル UI             | デスクトップアイコンから起動するコンソール風 GUI（Tkinter） |
| ポーリング間隔の動的変更         | 管理 UI から `interval <seconds>` で 0.1s 単位で変更可能       |

## ディレクトリ構成

```
omakase_notifier/
├── assets/                  # icon.ico を置くとショートカットに反映
├── config.example.yaml      # 設定テンプレート
├── data/                    # SQLite DB の置き場所（自動生成）
├── requirements.txt
├── scripts/
│   ├── install_windows.ps1  # 初期セットアップ＋デスクトップショートカット作成
│   ├── uninstall_windows.ps1
│   └── start.bat            # ショートカットから呼ばれる起動スクリプト
├── src/omakase_notifier/
│   ├── admin_ui/            # ターミナル風 GUI（Tkinter）
│   │   ├── app.py
│   │   └── commands.py
│   ├── crawler/             # Playwright クローラ
│   │   ├── omakase.py
│   │   └── calibrate.py     # セレクタ調整用ヘルパ
│   ├── notifier/            # メール / LINE 送信
│   ├── config.py
│   ├── db.py
│   ├── models.py
│   └── service.py           # スケジューラ＆コア処理
└── tests/
```

## セットアップ（Windows）

事前に **Python 3.11 以降** をインストールしてください
（公式インストーラから「Add python.exe to PATH」にチェック）。

```powershell
# プロジェクトルートで
git clone <this-repo> ClaudeCode
cd ClaudeCode\omakase_notifier
powershell -ExecutionPolicy Bypass -File scripts\install_windows.ps1
```

スクリプトが行うこと:

1. `.venv` を作成
2. `requirements.txt` の依存と Playwright の Chromium をインストール
3. `config.example.yaml` を `config.yaml` にコピー（既存はそのまま）
4. デスクトップに **「Omakase Notifier」** ショートカットを作成

ショートカットをダブルクリックするとターミナル風の管理 UI が起動し、
バックグラウンドでポーリングサービスも動き始めます。

### config.yaml を編集

`config.yaml` を開き、最低限以下を設定します:

- `email.smtp_*` および `from_address`
- LINE 通知を使うなら `line.channel_access_token`
- ポーリング間隔の初期値 `app.poll_interval_seconds`

## 管理コンソールの使い方

起動後、`omakase>` プロンプトに対して以下のコマンドが使えます。
`help` で一覧表示。

```text
help                                    コマンド一覧
status                                  サービス状態
start | stop                            ポーリングの開始 / 停止
interval <seconds>                      ポーリング間隔を変更（>= 0.1s）
refresh-list                            掲載店リストを今すぐ再取得

users add <name> [--email=X] [--line=Y] [--off]
users list
users remove <user_id>
users enable <user_id> | disable <user_id>

restaurants list [keyword]              掲載店一覧（キーワード検索可）
restaurants show <restaurant_id>

subscribe <user_id> <restaurant_id> [--email/--no-email] [--line/--no-line]
                                        [--min=N --max=M]
subscriptions list [user_id]
unsubscribe <subscription_id>

logs [count]                            直近の通知送信ログ
quit                                    UI 終了（サービスも停止）
```

### 典型的な手順（管理者）

```text
omakase> refresh-list
refreshed: 312 restaurants.

omakase> users add Taro --email=taro@example.com
added user id=1

omakase> restaurants list 鮨
ID    OMAKASE_ID           NAME
12    sushi-xxx            鮨◯◯
...

omakase> subscribe 1 12 --email --min=2 --max=4
subscribed: id=1
```

通知が飛ぶと `logs` コマンドで結果を確認できます。

## クローラのキャリブレーション

`crawler/omakase.py` の `LIST_SELECTORS` と `AVAILABILITY_SELECTORS` は
Omakase の DOM 構造に依存します。サイト構造が変わったとき、または初回
セットアップ時にセレクタを実機で確認するためのヘルパが付属しています。

```powershell
.\.venv\Scripts\python.exe -m omakase_notifier.crawler.calibrate list https://omakase.in/ja/restaurants
.\.venv\Scripts\python.exe -m omakase_notifier.crawler.calibrate availability https://omakase.in/ja/r/<id>
```

ブラウザが開いて要素候補が標準出力に出力されます。
適切なセレクタに合わせて `omakase.py` を編集してください。

## 通知が飛ぶ条件

ある (店舗 × 日時 × 人数) スロットについて:

- 直前の `AvailabilitySnapshot.available` が `False`（または未記録）で
- 今回のクロールで「空席あり」として検出された

この **立ち上がり** のタイミングで、その店舗を購読している全ユーザーに
それぞれの設定（メール / LINE / 人数レンジ）に従って通知します。

## 注意事項とロードマップ

- 本実装は **MVP** です。将来的な拡張候補:
  - LINE 友だち追加用の OAuth フロー（公式アカウント連携）
  - 管理者用の Web UI（Tkinter ではなく FastAPI ベース）
  - 通知メッセージのテンプレート機能
  - サービス化（`nssm` で Windows サービスとして常駐）
- 高頻度ポーリングはサーバへの負荷・規約違反になり得ます。
  既定の 300 秒（5 分）から大きく短くしないでください。
