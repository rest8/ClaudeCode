// 5項目ヒアリングのステートマシン。
// LINE 入力 (テキスト or 日付ピッカーの postback) を受けて、次の質問 or
// 最終レポートを LINE メッセージ配列として返す。

import type { LineMessage, LineQuickReplyItem } from "../line/types";
import type { FortuneRequest } from "../prompt";
import {
  parseBirthDate,
  parseGender,
  parseMbti,
  parseYesNo,
} from "./parser";
import {
  clearSession,
  getSession,
  Session,
  setSession,
  startSession,
} from "./session";

export interface ChatInput {
  text?: string;
  postbackDate?: string; // datetimepicker から
  isFollow?: boolean; // 友だち追加直後
}

export interface ChatTurn {
  immediate: LineMessage[]; // reply token で即時返信
  // generate が指定された場合、即時返信後に Claude を呼んで push する
  generate?: () => Promise<LineMessage[]>;
}

const RESET_KEYWORDS = ["リセット", "やり直し", "最初から", "reset"];
const HELP_KEYWORDS = ["ヘルプ", "help", "使い方"];

export function processChatInput(
  userId: string,
  input: ChatInput,
  generator: (req: FortuneRequest) => Promise<string>,
): ChatTurn {
  const text = (input.text ?? "").trim();

  if (input.isFollow) {
    startSession(userId);
    return { immediate: [greet(), askGender()] };
  }

  if (RESET_KEYWORDS.includes(text)) {
    startSession(userId);
    return {
      immediate: [
        textOnly("リセットしました。最初から鑑定を始めましょう ✨"),
        askGender(),
      ],
    };
  }

  if (HELP_KEYWORDS.includes(text)) {
    return { immediate: [helpMessage()] };
  }

  let session = getSession(userId);
  if (!session) {
    session = startSession(userId);
    return {
      immediate: [greet(), askGender()],
    };
  }

  switch (session.step) {
    case "ASK_GENDER":
      return handleGender(userId, session, text);
    case "ASK_BIRTHDATE":
      return handleBirthDate(userId, session, input);
    case "ASK_LEFT_HOME":
      return handleLeftHome(userId, session, text);
    case "ASK_SPOILED":
      return handleSpoiled(userId, session, text);
    case "ASK_MBTI":
      return handleMbti(userId, session, text, generator);
    case "GENERATING":
      return {
        immediate: [textOnly("ただいま鑑定中です…もう少々お待ちください ✨")],
      };
    case "DONE":
      // 完了後に何か送ってきたら、再開を提案
      return {
        immediate: [
          textOnly(
            "鑑定はすでに完了しています。もう一度占いたい場合は「リセット」と送ってください。",
          ),
        ],
      };
    default: {
      const _exhaustive: never = session.step;
      void _exhaustive;
      return { immediate: [textOnly("予期せぬ状態です。「リセット」と送ってください。")] };
    }
  }
}

function handleGender(userId: string, session: Session, text: string): ChatTurn {
  const g = parseGender(text);
  if (!g) {
    return {
      immediate: [
        retry("「男性」または「女性」を選んでください。"),
        askGender(),
      ],
    };
  }
  session.data.gender = g;
  session.step = "ASK_BIRTHDATE";
  setSession(userId, session);
  return { immediate: [askBirthDate()] };
}

function handleBirthDate(
  userId: string,
  session: Session,
  input: ChatInput,
): ChatTurn {
  const candidate = input.postbackDate ?? input.text ?? "";
  const iso = parseBirthDate(candidate);
  if (!iso) {
    return {
      immediate: [
        retry("生年月日を読み取れませんでした。下のボタンから日付を選んでください。"),
        askBirthDate(),
      ],
    };
  }
  session.data.birthDate = iso;
  session.step = "ASK_LEFT_HOME";
  setSession(userId, session);
  return {
    immediate: [
      textOnly(`生年月日: ${iso} で承りました。`),
      askLeftHome(),
    ],
  };
}

function handleLeftHome(
  userId: string,
  session: Session,
  text: string,
): ChatTurn {
  const ans = parseYesNo(text);
  if (ans === null) {
    return { immediate: [retry("「はい」か「いいえ」で答えてください。"), askLeftHome()] };
  }
  session.data.leftHomeAsTeen = ans;
  session.step = "ASK_SPOILED";
  setSession(userId, session);
  return { immediate: [askSpoiled()] };
}

function handleSpoiled(
  userId: string,
  session: Session,
  text: string,
): ChatTurn {
  const ans = parseYesNo(text);
  if (ans === null) {
    return { immediate: [retry("「はい」か「いいえ」で答えてください。"), askSpoiled()] };
  }
  session.data.raisedSpoiled = ans;
  session.step = "ASK_MBTI";
  setSession(userId, session);
  return { immediate: [askMbti()] };
}

function handleMbti(
  userId: string,
  session: Session,
  text: string,
  generator: (req: FortuneRequest) => Promise<string>,
): ChatTurn {
  const m = parseMbti(text);
  if (!m) {
    return {
      immediate: [
        retry(
          "MBTI を読み取れませんでした。INTJ・ENFP のように半角アルファベット 4 文字で送ってください。",
        ),
        askMbti(),
      ],
    };
  }
  session.data.mbti = m;
  session.step = "GENERATING";
  setSession(userId, session);

  const req = session.data as FortuneRequest;

  return {
    immediate: [
      textOnly(
        `${m} で承りました。\n${session.data.gender === "female" ? "あなた" : "あなた"}の星を読んでいます…✨\n（30秒ほどお待ちください）`,
      ),
    ],
    generate: async () => {
      try {
        const report = await generator(req);
        const session2 = getSession(userId);
        if (session2) {
          session2.step = "DONE";
          setSession(userId, session2);
        }
        return splitReport(report);
      } catch (err) {
        clearSession(userId);
        const msg = err instanceof Error ? err.message : "不明なエラー";
        return [
          textOnly(
            `申し訳ありません、鑑定中にエラーが発生しました。\n(${msg})\nしばらくしてから「リセット」と送って再度お試しください。`,
          ),
        ];
      }
    },
  };
}

// ---------- Message builders ----------

function textOnly(text: string): LineMessage {
  return { type: "text", text };
}

function retry(text: string): LineMessage {
  return { type: "text", text };
}

function greet(): LineMessage {
  return {
    type: "text",
    text: "はじめまして。占い師「縁(えにし)」です。\n恋暦オーラ × MBTI で、あなただけのレポートを紡ぎます。\n5つの質問にお答えくださいね 🔮",
  };
}

function helpMessage(): LineMessage {
  return {
    type: "text",
    text: [
      "【使い方】",
      "1. 5つの質問 (性別 / 生年月日 / 親元 / 育ち / MBTI) に答える",
      "2. AI 占い師「縁」がレポートを生成",
      "",
      "・最初からやり直したいときは「リセット」",
      "・MBTIが分からない方は https://www.16personalities.com/ja で診断可",
    ].join("\n"),
  };
}

function quickReply(items: LineQuickReplyItem[]): { items: LineQuickReplyItem[] } {
  return { items };
}

function msgAction(label: string, text: string): LineQuickReplyItem {
  return { type: "action", action: { type: "message", label, text } };
}

function askGender(): LineMessage {
  return {
    type: "text",
    text: "【1/5】性別を教えてください。",
    quickReply: quickReply([
      msgAction("女性", "女性"),
      msgAction("男性", "男性"),
    ]),
  };
}

function askBirthDate(): LineMessage {
  const today = new Date().toISOString().slice(0, 10);
  return {
    type: "text",
    text: "【2/5】生年月日を教えてください。\n(例: 1995-06-15 / 1995年6月15日)",
    quickReply: quickReply([
      {
        type: "action",
        action: {
          type: "datetimepicker",
          label: "日付を選ぶ",
          data: "birthdate",
          mode: "date",
          initial: "1995-01-01",
          min: "1900-01-01",
          max: today,
        },
      },
    ]),
  };
}

function askLeftHome(): LineMessage {
  return {
    type: "text",
    text: "【3/5】10代のうちに親元を離れて暮らしましたか？",
    quickReply: quickReply([
      msgAction("はい", "はい"),
      msgAction("いいえ", "いいえ"),
    ]),
  };
}

function askSpoiled(): LineMessage {
  return {
    type: "text",
    text: "【4/5】どちらかといえば甘やかされて育った、と感じますか？",
    quickReply: quickReply([
      msgAction("はい", "はい"),
      msgAction("いいえ", "いいえ"),
    ]),
  };
}

function askMbti(): LineMessage {
  return {
    type: "text",
    text:
      "【5/5】MBTI を 4 文字で教えてください。\n例: INFP / ENTJ / ESFP\n分からない方は https://www.16personalities.com/ja で診断できます。",
  };
}

// LINE は Markdown をレンダリングしないので、装飾を残したまま読みやすくする。
function markdownToLineText(md: string): string {
  return md
    .replace(/^####\s+(.*)$/gm, "▸ $1")
    .replace(/^###\s+(.*)$/gm, "▶ $1")
    .replace(/^##\s+(.*)$/gm, "■ $1")
    .replace(/^#\s+(.*)$/gm, "◆ $1")
    .replace(/\*\*(.+?)\*\*/g, "$1")
    .replace(/\*(.+?)\*/g, "$1")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/^\s*[-*]\s+/gm, "・")
    .replace(/^\s*>\s?/gm, "  ")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

// LINE のテキストメッセージは 5000 字まで。
// レポートは 1500 字程度なので 1 通で送れるはずだが、念のため分割。
function splitReport(report: string): LineMessage[] {
  const LIMIT = 4500;
  const text = markdownToLineText(report);
  if (text.length <= LIMIT) return [textOnly(text), tailMessage()];
  const parts: string[] = [];
  let rest = text;
  while (rest.length > LIMIT) {
    // 区切り文字 (改行) で切る
    let cut = rest.lastIndexOf("\n\n", LIMIT);
    if (cut < LIMIT * 0.5) cut = LIMIT;
    parts.push(rest.slice(0, cut));
    rest = rest.slice(cut).trimStart();
  }
  parts.push(rest);
  return [...parts.map(textOnly), tailMessage()];
}

function tailMessage(): LineMessage {
  return {
    type: "text",
    text: "もう一度占いたいときは「リセット」と送ってくださいね 🌙",
  };
}
