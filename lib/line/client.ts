import type { LineMessage } from "./types";

const BASE = "https://api.line.me/v2/bot";

function token(): string {
  const t = process.env.LINE_CHANNEL_ACCESS_TOKEN;
  if (!t) {
    throw new Error("LINE_CHANNEL_ACCESS_TOKEN が設定されていません。");
  }
  return t;
}

async function call(
  path: string,
  body: Record<string, unknown>,
): Promise<void> {
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token()}`,
    },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`LINE API ${path} failed: ${res.status} ${text}`);
  }
}

export async function reply(
  replyToken: string,
  messages: LineMessage[],
): Promise<void> {
  await call("/message/reply", { replyToken, messages });
}

export async function push(
  to: string,
  messages: LineMessage[],
): Promise<void> {
  await call("/message/push", { to, messages });
}
