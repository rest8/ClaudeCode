# Omakase Auto-Booker

Omakase（omakase.in）の飲食店予約を自動化するPythonプログラムです。
Google カレンダーの空きスケジュール、またはユーザー指定の候補日をもとに、対象レストランの予約枠が開いたタイミングで自動予約・決済を行います。

## 動作フロー

1. **Google カレンダーチェック** → 希望時間帯（18:00, 19:00等）に空きがある日を特定
2. **候補日の決定** → ユーザー指定の `candidate_dates` またはカレンダーの空き日
3. **Omakase 空き確認** → 対象レストランのページで予約可能枠を確認し、予約開始時刻を自動検出
4. **マッチング** → 候補日 × Omakase の空き枠が一致したら即予約
5. **高速ポーリング** → 予約開始時刻（レストランごとに自動検出）前後は0.5秒間隔で監視
6. **決済** → 予約枠を確保したら席予約手数料の決済を実行

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
- 候補日（`candidate_dates`）を指定するか、カレンダー連携で自動判定
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
    booking_mode: "first_come"
    candidate_dates:           # 候補日を直接指定（省略時はカレンダーから自動判定）
      - "2026-04-15"
      - "2026-04-16"
```

## 予約方式

Omakase には2つの予約方式があり、レストランごとに異なります：

### 先着順（`booking_mode: "first_come"`）
- 予約開始時刻に枠が公開され、先着順で確保
- 予約開始時刻はレストランページから自動検出
- 開始時刻の前後5分間は0.5秒間隔の高速ポーリングで対応

### 抽選制（`booking_mode: "lottery"`）
- 人気店で採用。予約開始の約1週間前からエントリー受付
- 24時間ごとに1回エントリー可能（回数が多いほど当選率UP）
- 当選者は優先予約枠（約1時間）で日時を選択
- 本ツールは自動エントリーと当選確認・自動予約に対応

## 候補日の指定

2つの方法で候補日を決定できます：

### 方法1: 直接指定（`candidate_dates`）
`config.yaml` で候補日を直接指定します。カレンダーチェックをスキップします。

```yaml
candidate_dates:
  - "2026-04-15"
  - "2026-04-16"
  - "2026-04-22"
```

### 方法2: Google カレンダー自動判定
`candidate_dates` を省略すると、Google カレンダーの空き時間から候補日を自動判定します。

## 注意事項

- **利用規約**: Omakase (omakase.in) の利用規約では、ボット・自動操作・プログラムによるアクセスが明示的に禁止されています（第16条）。本ツールの使用は自己責任です。アカウント停止のリスクがあります
- 予約時に席予約手数料（通常 ¥390/人）がクレジットカードに課金されます
- 来店時に写真付き身分証明書の提示が必要です（予約者名と一致しない場合、入店拒否+キャンセル料100%）
- `config.yaml`, `credentials.json`, `token.json` は `.gitignore` に含まれており、コミットされません
- `headless: false` に設定するとブラウザの動作を目視確認できます（デバッグ用）
- Omakase のUI変更により動作しなくなる場合があります。その場合は `omakase_client.py` のセレクタを調整してください
