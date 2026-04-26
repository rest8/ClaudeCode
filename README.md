# Hermes 在庫監視 → Google Chat 通知

Hermes オンラインを定期巡回し、以下 6 種が在庫ありになった瞬間に **Google Chat** へリンク付きで通知します。

| # | 監視対象 | 検索キー |
|---|---------|----------|
| 1 | ケリー       | kelly      |
| 2 | バーキン     | birkin     |
| 3 | ピコタン     | picotin    |
| 4 | コンスタンス | constance  |
| 5 | エヴリン     | evelyne    |
| 6 | アッカド     | akkad      |

## セットアップ

```bash
pip install -r requirements.txt
```

Google Chat スペースで **Webhook** を作成し URL を取得:
スペース設定 → アプリと統合 → Webhook を追加

```bash
export GOOGLE_CHAT_WEBHOOK="https://chat.googleapis.com/v1/spaces/XXX/messages?key=...&token=..."
```

## 実行

```bash
# デフォルト: 1秒ごと巡回 (ご指定通り)
python3 hermes_monitor.py

# 推奨: 30秒間隔 (ブロック回避)
python3 hermes_monitor.py --interval 30

# ロケール変更 (例: フランス本国)
python3 hermes_monitor.py --locale fr/fr
```

## 動作概要

1. Hermes 検索 API (`/api/{locale}/products/search`) を 6 キーワードで順に巡回
2. レスポンスから `available: true` の SKU を抽出
3. **未通知の SKU** だけを Google Chat にカード形式で通知（タイトル・価格・商品URL 付き）
4. 同一 SKU は 1 時間クールダウン（再入荷検知のため永続ブラックリスト化はしない）
5. API がブロックされた場合は HTML 検索ページの `__NEXT_DATA__` を解析してフォールバック

## ⚠ 重要な注意

- **1秒間隔は Hermes の利用規約違反の可能性が高く、IPブロック・法的リスクがあります**
- Hermes は強力なボット対策（Akamai Bot Manager 等）を導入しています
- 長期運用するなら `--interval 30` 以上を推奨します
- 個人利用の範囲で、自己責任にてご利用ください

## テスト

```bash
pip install pytest
pytest test_hermes_monitor.py -v
```
