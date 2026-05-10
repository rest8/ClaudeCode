# 恋暦 × MBTI 占術

恋暦占術 ([renreki.com](https://renreki.com/)) の世界観と MBTI を融合させ、
ユーザーごとにオリジナルの恋愛・人間関係レポートを Claude API で生成する
Next.js アプリです。

> ⚠️ 本家「恋暦占術」のアルゴリズム自体は非公開です。本リポジトリの
> オーラ判定は **公開情報を踏まえた独自の決定論的近似** であり、
> 本家サイトでの鑑定結果とは一致しません。ファンメイドの実験プロジェクトです。

## 入力項目

1. **性別** (男性 / 女性)
2. **生年月日**
3. **10代で親元を離れて暮らしたか** (はい / いいえ)
4. **どちらかといえば甘やかされて育ったか** (はい / いいえ)
5. **MBTI** (16タイプから選択)

## 出力

- 12 オーラ (6 基本タイプ × 強弱) のうちあなたに最も近い 1 つ
- 親元・育ちフラグを反映した「基本気質」の説明
- MBTI と掛け合わせた **独自レポート** (Markdown / 5 セクション構成)
  1. 基本気質 (恋暦オーラ × 育ち)
  2. MBTI としての思考と行動パターン
  3. オーラ × MBTI の独自シナジー (3 つのキーワード)
  4. 恋愛・人間関係での処方箋 (強み / 注意点 / 相性 / 小さな一歩)
  5. 年齢に応じた一言

## 技術スタック

- Next.js 14 (App Router) / React 18 / TypeScript
- Tailwind CSS
- Anthropic Claude SDK (`@anthropic-ai/sdk`)
- 既定モデル: `claude-sonnet-4-6` (環境変数で上書き可)

## セットアップ

```bash
# 1. 依存をインストール
npm install

# 2. API キーを設定
cp .env.example .env.local
# .env.local の ANTHROPIC_API_KEY=... を実際のキーに書き換える

# 3. 開発サーバ起動
npm run dev
# → http://localhost:3000
```

## 主なファイル

| パス | 役割 |
| --- | --- |
| `app/page.tsx` | 入力フォーム & レポート表示画面 (Web版) |
| `app/api/fortune/route.ts` | Web フォームから呼ばれる Claude API エンドポイント |
| `app/api/line/webhook/route.ts` | LINE Messaging API の Webhook 受け口 |
| `lib/renreki.ts` | 12 オーラ判定の決定論的ロジック |
| `lib/mbti.ts` | 16 MBTI タイプの定義 |
| `lib/prompt.ts` | Claude へのシステム / ユーザープロンプト |
| `lib/fortune.ts` | Renreki + Claude を呼んでレポート生成 (Web/LINE 共通) |
| `lib/chat/session.ts` | LINE Bot のインメモリ会話セッション |
| `lib/chat/flow.ts` | 5 項目ヒアリングのステートマシン & メッセージ生成 |
| `lib/chat/parser.ts` | ユーザー入力 (性別/日付/MBTI など) のパーサ |
| `lib/line/*` | LINE Messaging API の最小クライアント & 署名検証 |
| `lib/markdown.ts` | 軽量な Markdown レンダラ (Web版) |
| `components/FortuneForm.tsx` | Web 版の 5 項目入力フォーム |
| `components/FortuneResult.tsx` | Web 版のオーラサマリ & レポート表示 |

## LINE Bot として動かす

Web フォームに加え、LINE 上で AI 占い師「縁」が 5 項目をヒアリング → 鑑定結果を
返すモードも同梱しています。

### 1. LINE Developers でチャネルを作る

1. https://developers.line.biz/console/ にログイン
2. プロバイダー → 新規チャネル → **Messaging API** を作成
3. 作成後、以下を控える:
   - **Channel secret** (Basic settings)
   - **Channel access token (long-lived)** (Messaging API → 「発行」)
4. **応答メッセージ / あいさつメッセージは OFF**、**Webhook 利用は ON** に設定

### 2. Webhook URL を設定

公開された HTTPS URL の `/api/line/webhook` を Webhook URL に登録します。

- 本番: 例 `https://<your-domain>/api/line/webhook` (Vercel など)
- ローカル開発: [ngrok](https://ngrok.com/) などでトンネル
  ```bash
  ngrok http 3000
  # → https://xxxx.ngrok-free.app/api/line/webhook を Webhook URL に設定
  ```

### 3. 環境変数

`.env.local` に下記を追加:

```bash
LINE_CHANNEL_SECRET=...
LINE_CHANNEL_ACCESS_TOKEN=...
```

### 4. 友だち追加 → ヒアリング開始

LINE 公式アカウントを友だち追加して話しかけると、

1. 性別 (クイックリプライ: 男性 / 女性)
2. 生年月日 (日付ピッカー or テキスト)
3. 10代で親元を離れたか (はい / いいえ)
4. 甘やかされて育ったか (はい / いいえ)
5. MBTI (4 文字のテキスト入力)

を順に聞かれ、回答が揃うと Claude が鑑定レポートを送り返します。

### 注意事項 (LINE Bot)

- 会話状態は **インメモリ** で保持しているため、サーバ再起動 / コールドスタートで消えます。本番では Redis などへ差し替えてください。
- Vercel の Hobby プランでは最大関数実行時間が短いため、Claude の応答が遅いとタイムアウトすることがあります。`ANTHROPIC_MODEL=claude-haiku-4-5-20251001` に切り替える、もしくは Pro プランへ変更を検討してください。
- Webhook の署名検証は HMAC-SHA256 で行っています (`lib/line/verify.ts`)。

## 12 オーラ一覧 (本実装でのマッピング)

| 基本タイプ | 強 | 弱 |
| --- | --- | --- |
| 奇人系 | 赤 | オレンジ |
| クール系 | 青 | 水色 |
| 慎重系 | 緑 | 黄緑 |
| 自由人系 | 紫 | 紺 |
| 努力家系 | 茶 | グレー |
| ムード系 | ピンク | 黄 |

「親元を離れた / 甘やかされた」のフラグはオーラ自体は変えず、
気質の表れ方を **プロンプトで Claude に伝えて** レポートに反映させます。

## ライセンス & 注意事項

- 本リポジトリ自体はサンプル / 個人利用想定です。
- 「恋暦占術」「Renreki」は本家サイト運営者の表現です。本プロジェクトは
  本家とは無関係なファンメイド実装で、商用利用は想定していません。
