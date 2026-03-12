# Omakase Auto-Booker

Omakase（omakase.in）の飲食店予約を自動化するWindows デスクトップアプリです。
Google カレンダーと連携し、カレンダー上で候補日を選択 → 自動予約 → 予約完了後にカレンダーへ自動登録を行います。

## 動作フロー

1. **アプリ起動** → カレンダーが表示され、Google カレンダーの予定が同期表示
2. **候補日選択** → カレンダー上で予約候補日をクリック（黄色でマーク）
3. **予約開始** → 「予約開始」ボタンで自動予約処理を開始
4. **Omakase 空き確認** → レストランページで空き枠を確認 + 予約開始時刻を自動検出
5. **高速ポーリング** → 予約開始時刻前後は0.5秒間隔で監視
6. **予約枠確保** → 候補日 × 空き枠が一致したら即座に予約枠を確保
7. **承認依頼** → Google Chat で決済の承認依頼を送信、ユーザーが承認/却下
8. **決済実行** → 承認後に席予約手数料の決済を実行
9. **カレンダー登録** → 予約完了後、Google カレンダーに予定を自動追加（緑でマーク）

## セットアップ

### 方法1: Python から実行

```bash
pip install -r requirements.txt
playwright install chromium
python -m omakase_booker
```

### 方法2: Windows .exe（ビルド）

```bat
build.bat
```

`dist\OmakaseBooker.exe` が生成されます。ダブルクリックで起動。

### Google Calendar API の設定

1. [Google Cloud Console](https://console.cloud.google.com/) でプロジェクトを作成
2. Google Calendar API を有効化
3. OAuth 2.0 クライアント ID を作成（デスクトップアプリ）
4. `credentials.json` をプロジェクトルートにダウンロード

### 設定ファイルの作成

```bash
cp config.example.yaml config.yaml
```

`config.yaml` を編集し、以下を設定:
- Omakase のメールアドレス・パスワード
- 予約したいレストランのURL・人数・希望時間

## GUI の使い方

### カレンダー
- **青**: Google カレンダーの既存予定
- **黄**: 選択した予約候補日（クリックで追加/解除）
- **緑**: 予約済みの日

### 操作手順
1. 左のカレンダーで候補日をクリック（複数選択可）
2. 右パネルでレストランを選択
3. 「予約開始」ボタンをクリック
4. 自動で空き枠監視→マッチ→予約枠確保
5. **Google Chat で承認依頼**が届く（または GUI ダイアログ）
6. 承認後に決済実行→カレンダー登録

### CLI モード

GUIを使わずCLIで実行する場合:

```bash
python -m omakase_booker --cli
```

## 設定例

```yaml
target_restaurants:
  - name: "鮨 さいとう"
    omakase_url: "https://omakase.in/r/example123"
    party_size: 2
    preferred_times:
      - "18:00"
      - "19:00"
    booking_mode: "first_come"
```

## 予約方式

### 先着順（`booking_mode: "first_come"`）
- 予約開始時刻に枠が公開され、先着順で確保
- 予約開始時刻はレストランページから自動検出
- 開始時刻の前後5分間は0.5秒間隔の高速ポーリング

### 抽選制（`booking_mode: "lottery"`）
- 人気店で採用。予約開始の約1週間前からエントリー受付
- 24時間ごとに1回エントリー可能（回数が多いほど当選率UP）
- 当選者は優先予約枠（約1時間）で日時を選択
- 自動エントリーと当選確認・自動予約に対応

## 決済前の承認フロー

予約枠を確保した後、決済の前に Google Chat で承認依頼を送信します。

### 設定方法

1. Google Chat でスペースを作成（またはDM）
2. Webhook を追加（スペース設定 → アプリと統合 → Webhook）
3. Webhook URL を `config.yaml` の `gchat_webhook_url` に設定

```yaml
gchat_webhook_url: "https://chat.googleapis.com/v1/spaces/XXXX/messages?key=..."
gchat_callback_url: "https://your-ngrok-url.ngrok.io"  # ボタン付きカードを使う場合
approval_timeout_seconds: 300
```

### 動作の流れ

1. 予約枠確保後、Google Chat にカード形式の承認依頼が届く
2. カードには レストラン名、日時、人数、手数料 が表示される
3. 「承認」ボタンをクリック → 決済が実行される
4. 「却下」ボタンをクリック → 決済をスキップ
5. タイムアウト（デフォルト5分）の場合、アプリ上のダイアログにフォールバック

### Google Chat を使わない場合

`gchat_webhook_url` を空にすると、アプリ上の確認ダイアログ（GUI）またはCLIプロンプトで承認を求めます。

## 注意事項

- **利用規約**: Omakase (omakase.in) の利用規約では、ボット・自動操作・プログラムによるアクセスが明示的に禁止されています（第16条）。本ツールの使用は自己責任です。アカウント停止のリスクがあります
- 予約時に席予約手数料（通常 ¥390/人）がクレジットカードに課金されます
- 来店時に写真付き身分証明書の提示が必要です（予約者名と一致しない場合、入店拒否+キャンセル料100%）
- `config.yaml`, `credentials.json`, `token.json` は `.gitignore` に含まれており、コミットされません
- `headless: false` に設定するとブラウザの動作を目視確認できます（デバッグ用）
- Omakase のUI変更により動作しなくなる場合があります。その場合は `omakase_client.py` のセレクタを調整してください
