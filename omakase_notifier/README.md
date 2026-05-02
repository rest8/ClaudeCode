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
│   ├── webapp/              # iOS 風 Web UI（FastAPI + 静的資産）
│   │   ├── app.py           # REST API
│   │   ├── templates/index.html
│   │   └── static/{css,js}
│   ├── desktop.py           # pywebview ネイティブウィンドウ起動
│   ├── crawler/             # Playwright クローラ
│   │   ├── omakase.py
│   │   └── calibrate.py     # セレクタ調整用ヘルパ
│   ├── notifier/            # メール / LINE 送信
│   ├── bootstrap.py         # 初回起動時のデスクトップショートカット作成
│   ├── config.py
│   ├── db.py
│   ├── models.py
│   └── service.py           # スケジューラ＆コア処理
└── tests/
```

## セットアップ（Windows）

事前に **Python 3.12 / 3.13 / 3.14** のいずれかをインストールしてください
（公式インストーラから「Add python.exe to PATH」にチェック）。

### 推奨: ワンステップインストーラ

```powershell
git clone <this-repo> ClaudeCode
cd ClaudeCode\omakase_notifier
powershell -ExecutionPolicy Bypass -File scripts\install_windows.ps1
```

スクリプトが行うこと:

1. `.venv` を作成
2. `requirements.txt` の依存と Playwright の Chromium をインストール
3. `config.example.yaml` を `config.yaml` にコピー（既存はそのまま）
4. デスクトップに **「Omakase Notifier」** ショートカットを作成

### 手動セットアップでも可

`pip install` を直接使った場合、デスクトップショートカットは
**初回起動時にアプリが自動作成** します。手順は次の通りです:

```powershell
cd ClaudeCode\omakase_notifier
pip install -r requirements.txt
python -m playwright install chromium
copy config.example.yaml config.yaml
notepad config.yaml             # SMTP / LINE 等を設定
python launcher.py              # ← 初回はここから起動。終了後デスクトップにアイコンが出来る
```

### ネイティブ風ウィンドウで開きたい場合（任意）

既定では **既定ブラウザのタブ** で開きます。WebView2 ベースの
ネイティブ風ウィンドウ（タイトルバーだけのスッキリしたアプリ風）に
したい場合は追加で:

```powershell
pip install -r requirements-desktop.txt
```

> **2026-05 時点の注意**: 内部依存の `pythonnet` がまだ Python 3.14 用の
> wheel を出していないため、3.14 ではこのインストールが失敗します。
> ネイティブウィンドウを使いたい場合は **Python 3.13** で動かしてください。
> 失敗してもアプリ自体は問題なくブラウザモードで動きます。

### 起動方法（初回／2回目以降ともに）

- **初回**: `python launcher.py`、または `install_windows.ps1` 実行直後
  に作成されるデスクトップアイコンをダブルクリック
- **2回目以降**: デスクトップの **「Omakase Notifier」** をダブルクリック

ショートカットが消えた／別 PC へ移したときは、もう一度 `python launcher.py`
を実行すれば再生成されます（既存があれば何もしません）。

### 初回設定

初回起動はそのまま `config.yaml` が空のままでも UI は立ち上がりますが、
**右上の歯車アイコン → 設定** から以下を入れてください:

- SMTP (`smtp_host` / `smtp_port` / `smtp_user` / `smtp_password` / `from_address`)
- LINE 通知を使うなら **Channel access token**
- ポーリング間隔（既定 300 秒 / 0.1 秒単位で変更可）

設定は `config.yaml` に書き戻されるので、再起動しても保持されます。

## UI の使い方

下部のタブバーで 3 画面を切り替えます。

| タブ | 内容 |
| --- | --- |
| **ホーム** | 月ビューカレンダー。空席のある日付に● ドットが付く。日付タップで店舗・時間・人数・料金・キャンセル規定を一覧表示 |
| **店舗** | Omakase 掲載店の全件リスト（名称・エリア・ジャンル）。検索 + 「リスト更新」ボタン。行タップで購読ユーザーをチェックボックスで切替 |
| **ユーザー** | ユーザーの追加 / 編集 / 削除。メール・LINE ID・有効/無効スイッチ。各ユーザーの購読店舗を追加 / 解除 |

カレンダーの● ドットは、**全ユーザーが購読している店舗の空席状況**
（≒ 実際にサービスがポーリングしているデータ）を反映します。
未購読の店舗は空席判定の対象外です。

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
  - 通知メッセージのテンプレート機能
  - サービス化（`nssm` で Windows サービスとして常駐 / システムトレイ常駐）
  - クローラのジャンル抽出強化（`Restaurant.genre` を Omakase の DOM から取得）
- 高頻度ポーリングはサーバへの負荷・規約違反になり得ます。
  既定の 300 秒（5 分）から大きく短くしないでください。
- pywebview は内部的に Edge WebView2 を利用します。Win10/11 にはほぼ標準で
  入っていますが、未インストール環境では Microsoft の WebView2 ランタイムを
  別途インストールしてください。失敗した場合は既定ブラウザで `localhost`
  に自動フォールバックします。
