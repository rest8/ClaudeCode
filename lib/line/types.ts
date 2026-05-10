// LINE Messaging API のうち、本 Bot が利用する範囲だけを型として定義する。
// 公式 SDK を入れずに最小依存で実装するための内部型。

export interface LineSource {
  type: "user" | "group" | "room";
  userId?: string;
}

export interface LineTextMessageEvent {
  type: "message";
  replyToken: string;
  source: LineSource;
  message: { type: "text"; id: string; text: string };
}

export interface LinePostbackEvent {
  type: "postback";
  replyToken: string;
  source: LineSource;
  postback: {
    data: string;
    params?: { date?: string; time?: string; datetime?: string };
  };
}

export interface LineFollowEvent {
  type: "follow";
  replyToken: string;
  source: LineSource;
}

export type LineWebhookEvent =
  | LineTextMessageEvent
  | LinePostbackEvent
  | LineFollowEvent
  | { type: string; replyToken?: string; source?: LineSource }; // unknown others

export interface LineQuickReplyMessageAction {
  type: "action";
  action: {
    type: "message";
    label: string;
    text: string;
  };
}

export interface LineQuickReplyDatetimeAction {
  type: "action";
  action: {
    type: "datetimepicker";
    label: string;
    data: string;
    mode: "date";
    initial?: string;
    max?: string;
    min?: string;
  };
}

export type LineQuickReplyItem =
  | LineQuickReplyMessageAction
  | LineQuickReplyDatetimeAction;

export interface LineTextMessage {
  type: "text";
  text: string;
  quickReply?: { items: LineQuickReplyItem[] };
}

export type LineMessage = LineTextMessage;
