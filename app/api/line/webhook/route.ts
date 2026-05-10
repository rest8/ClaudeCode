import { NextRequest, NextResponse } from "next/server";
import { processChatInput } from "@/lib/chat/flow";
import { generateFortune } from "@/lib/fortune";
import * as line from "@/lib/line/client";
import type { LineWebhookEvent } from "@/lib/line/types";
import { verifyLineSignature } from "@/lib/line/verify";
import type { FortuneRequest } from "@/lib/prompt";

export const runtime = "nodejs";

export async function POST(req: NextRequest) {
  const channelSecret = process.env.LINE_CHANNEL_SECRET;
  const accessToken = process.env.LINE_CHANNEL_ACCESS_TOKEN;
  const apiKey = process.env.ANTHROPIC_API_KEY;

  if (!channelSecret || !accessToken) {
    return NextResponse.json(
      { error: "LINE_CHANNEL_SECRET / LINE_CHANNEL_ACCESS_TOKEN が未設定です。" },
      { status: 500 },
    );
  }
  if (!apiKey) {
    return NextResponse.json(
      { error: "ANTHROPIC_API_KEY が未設定です。" },
      { status: 500 },
    );
  }

  const rawBody = await req.text();
  const signature = req.headers.get("x-line-signature");
  if (!verifyLineSignature(rawBody, signature, channelSecret)) {
    return NextResponse.json({ error: "Invalid signature." }, { status: 401 });
  }

  let payload: { events?: LineWebhookEvent[] };
  try {
    payload = JSON.parse(rawBody);
  } catch {
    return NextResponse.json({ error: "Invalid JSON" }, { status: 400 });
  }

  const events = payload.events ?? [];

  // 処理は順番に行う。失敗してもログに留めて 200 を返す (LINE のリトライ抑止)。
  await Promise.all(events.map((e) => handleEvent(e, apiKey).catch((err) => {
    console.error("[line-webhook] event handling failed", err);
  })));

  return NextResponse.json({ ok: true });
}

async function handleEvent(event: LineWebhookEvent, apiKey: string): Promise<void> {
  const userId = event.source?.userId;
  if (!userId) return;

  let chatInput: { text?: string; postbackDate?: string; isFollow?: boolean } | null = null;
  let replyToken: string | undefined;

  if (event.type === "follow") {
    chatInput = { isFollow: true };
    replyToken = (event as { replyToken?: string }).replyToken;
  } else if (event.type === "message") {
    const m = (event as { message?: { type?: string; text?: string } }).message;
    if (m?.type !== "text" || typeof m.text !== "string") return;
    chatInput = { text: m.text };
    replyToken = (event as { replyToken?: string }).replyToken;
  } else if (event.type === "postback") {
    const pb = (event as {
      postback?: { data?: string; params?: { date?: string } };
    }).postback;
    chatInput = {
      text: pb?.data,
      postbackDate: pb?.params?.date,
    };
    replyToken = (event as { replyToken?: string }).replyToken;
  } else {
    return;
  }

  if (!replyToken || !chatInput) return;

  const turn = processChatInput(userId, chatInput, async (req: FortuneRequest) => {
    const { report } = await generateFortune(req, apiKey);
    return report;
  });

  // 即時メッセージを reply で返す
  try {
    await line.reply(replyToken, turn.immediate);
  } catch (err) {
    console.error("[line-webhook] reply failed", err);
  }

  // 鑑定生成が必要な場合は push で続報
  if (turn.generate) {
    try {
      const messages = await turn.generate();
      if (messages.length > 0) {
        await line.push(userId, messages);
      }
    } catch (err) {
      console.error("[line-webhook] push failed", err);
      try {
        await line.push(userId, [
          {
            type: "text",
            text: "鑑定の送信に失敗しました。少し時間をおいて「リセット」と送ってお試しください 🙏",
          },
        ]);
      } catch {
        /* ignore */
      }
    }
  }
}
