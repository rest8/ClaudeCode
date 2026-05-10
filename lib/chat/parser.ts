import { MBTI_TYPES, MbtiType } from "../mbti";

export function parseGender(text: string): "male" | "female" | null {
  const t = text.trim().toLowerCase();
  if (["女性", "女", "おんな", "female", "f", "w"].includes(t)) return "female";
  if (["男性", "男", "おとこ", "male", "m"].includes(t)) return "male";
  return null;
}

export function parseYesNo(text: string): boolean | null {
  const t = text.trim().toLowerCase();
  if (["はい", "yes", "y", "ある", "離れた", "そう", "うん"].some((k) => t === k)) {
    return true;
  }
  if (["いいえ", "no", "n", "ない", "離れてない", "ちがう", "違う"].some((k) => t === k)) {
    return false;
  }
  return null;
}

export function parseBirthDate(text: string): string | null {
  const t = text.trim();

  // ISO yyyy-mm-dd or yyyy/mm/dd
  let m = /^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})$/.exec(t);
  if (!m) {
    // 1995年6月15日 / 1995年06月15日
    m = /^(\d{4})年\s?(\d{1,2})月\s?(\d{1,2})日?$/.exec(t);
  }
  if (!m) return null;

  const y = Number(m[1]);
  const mo = Number(m[2]);
  const d = Number(m[3]);
  if (
    y < 1900 ||
    y > new Date().getFullYear() ||
    mo < 1 || mo > 12 ||
    d < 1 || d > 31
  ) {
    return null;
  }
  const dt = new Date(`${y}-${String(mo).padStart(2, "0")}-${String(d).padStart(2, "0")}`);
  if (
    Number.isNaN(dt.getTime()) ||
    dt.getUTCFullYear() !== y ||
    dt.getUTCMonth() + 1 !== mo ||
    dt.getUTCDate() !== d
  ) {
    return null;
  }
  return `${y}-${String(mo).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
}

export function parseMbti(text: string): MbtiType | null {
  const t = text.trim().toUpperCase().replace(/[\s\-_／/]/g, "");
  if ((MBTI_TYPES as readonly string[]).includes(t)) {
    return t as MbtiType;
  }
  // 中に含まれていたら拾う (例: "私は ENFP です" → ENFP)
  for (const code of MBTI_TYPES) {
    if (t.includes(code)) return code;
  }
  return null;
}
