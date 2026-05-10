import { NextRequest, NextResponse } from "next/server";
import { generateFortune } from "@/lib/fortune";
import { MBTI_TYPES, MbtiType } from "@/lib/mbti";
import { FortuneRequest } from "@/lib/prompt";

export const runtime = "nodejs";

function parseBody(body: unknown): FortuneRequest | { error: string } {
  if (!body || typeof body !== "object") {
    return { error: "リクエストボディが不正です。" };
  }
  const b = body as Record<string, unknown>;

  const gender = b.gender;
  if (gender !== "male" && gender !== "female") {
    return { error: "性別は 'male' または 'female' を指定してください。" };
  }

  const birthDate = b.birthDate;
  if (typeof birthDate !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(birthDate)) {
    return { error: "生年月日は yyyy-mm-dd 形式で指定してください。" };
  }
  const dateObj = new Date(birthDate);
  if (Number.isNaN(dateObj.getTime())) {
    return { error: "生年月日の値が不正です。" };
  }
  const year = Number(birthDate.slice(0, 4));
  if (year < 1900 || year > new Date().getFullYear()) {
    return { error: "生年月日の年が範囲外です。" };
  }

  const leftHomeAsTeen = b.leftHomeAsTeen;
  const raisedSpoiled = b.raisedSpoiled;
  if (typeof leftHomeAsTeen !== "boolean" || typeof raisedSpoiled !== "boolean") {
    return { error: "boolean フラグが欠けています。" };
  }

  const mbti = b.mbti;
  if (typeof mbti !== "string" || !MBTI_TYPES.includes(mbti as MbtiType)) {
    return { error: "MBTI が不正です。" };
  }

  return {
    gender,
    birthDate,
    leftHomeAsTeen,
    raisedSpoiled,
    mbti: mbti as MbtiType,
  };
}

export async function POST(req: NextRequest) {
  const apiKey = process.env.ANTHROPIC_API_KEY;
  if (!apiKey) {
    return NextResponse.json(
      { error: "ANTHROPIC_API_KEY が設定されていません。.env.local を確認してください。" },
      { status: 500 },
    );
  }

  let body: unknown;
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "JSON のパースに失敗しました。" }, { status: 400 });
  }

  const parsed = parseBody(body);
  if ("error" in parsed) {
    return NextResponse.json({ error: parsed.error }, { status: 400 });
  }

  try {
    const outcome = await generateFortune(parsed, apiKey);
    return NextResponse.json(outcome);
  } catch (err) {
    const msg = err instanceof Error ? err.message : "Claude API 呼び出しに失敗しました。";
    return NextResponse.json({ error: msg }, { status: 502 });
  }
}
