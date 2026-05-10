// インメモリの会話セッション。サーバ再起動で消える前提のデモ用ストア。
//
// LINE Bot のヒアリングは数ターンで完結するため、ユーザーごとの状態を
// Map に保持するだけで十分。本番運用では Redis などへ差し替える想定。

import type { FortuneRequest } from "../prompt";

export type Step =
  | "ASK_GENDER"
  | "ASK_BIRTHDATE"
  | "ASK_LEFT_HOME"
  | "ASK_SPOILED"
  | "ASK_MBTI"
  | "GENERATING"
  | "DONE";

export interface Session {
  step: Step;
  data: Partial<FortuneRequest>;
  updatedAt: number;
}

const TTL_MS = 30 * 60 * 1000; // 30 分

const sessions = new Map<string, Session>();

export function getSession(userId: string): Session | undefined {
  const s = sessions.get(userId);
  if (!s) return undefined;
  if (Date.now() - s.updatedAt > TTL_MS) {
    sessions.delete(userId);
    return undefined;
  }
  return s;
}

export function setSession(userId: string, session: Session): void {
  session.updatedAt = Date.now();
  sessions.set(userId, session);
}

export function clearSession(userId: string): void {
  sessions.delete(userId);
}

export function startSession(userId: string): Session {
  const session: Session = {
    step: "ASK_GENDER",
    data: {},
    updatedAt: Date.now(),
  };
  sessions.set(userId, session);
  return session;
}
