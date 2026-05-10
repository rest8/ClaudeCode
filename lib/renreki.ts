// 恋暦占術 風 オーラ判定ロジック (独自近似)
//
// 本家「恋暦占術」(https://renreki.com) は数十年の統計に基づく独自アルゴリズム
// で、内部ロジックは非公開です。本実装は公開情報 (12オーラ = 6基本タイプ ×
// 強弱) を踏まえた独自の決定論的近似で、本家の鑑定結果とは一致しません。

export type Gender = "male" | "female";

export type AuraColor =
  | "red"
  | "orange"
  | "blue"
  | "lightblue"
  | "green"
  | "yellowgreen"
  | "purple"
  | "navy"
  | "brown"
  | "gray"
  | "pink"
  | "yellow";

export type AuraGroup =
  | "eccentric"
  | "cool"
  | "cautious"
  | "freeSpirit"
  | "hardWorker"
  | "moody";

export type Polarity = "strong" | "weak";

export interface AuraProfile {
  group: AuraGroup;
  groupLabel: string;
  polarity: Polarity;
  color: AuraColor;
  colorLabel: string;
  catchphrase: string;
  coreTraits: string[];
  loveTendency: string;
}

export interface RenrekiInput {
  gender: Gender;
  birthDate: string; // ISO yyyy-mm-dd
  leftHomeAsTeen: boolean;
  raisedSpoiled: boolean;
}

export interface RenrekiResult {
  aura: AuraProfile;
  modifiers: {
    leftHomeAsTeen: boolean;
    raisedSpoiled: boolean;
    independenceNote: string;
    nurtureNote: string;
  };
  basics: {
    gender: Gender;
    birthDate: string;
    age: number;
    zodiacAnimal: string; // 干支
    westernZodiac: string; // 12星座
  };
}

const GROUP_DEFINITIONS: Record<
  AuraGroup,
  {
    label: string;
    strong: { color: AuraColor; colorLabel: string };
    weak: { color: AuraColor; colorLabel: string };
    catchphrase: { strong: string; weak: string };
    coreTraits: string[];
    loveTendency: string;
  }
> = {
  eccentric: {
    label: "奇人系",
    strong: { color: "red", colorLabel: "赤" },
    weak: { color: "orange", colorLabel: "オレンジ" },
    catchphrase: {
      strong: "情熱が暴走する天才肌",
      weak: "明るく愛されるトリックスター",
    },
    coreTraits: ["独創的", "衝動的", "好奇心旺盛", "場の空気を変える"],
    loveTendency:
      "刺激と意外性を求める恋。退屈すると一気に冷めるが、本気のときは一直線。",
  },
  cool: {
    label: "クール系",
    strong: { color: "blue", colorLabel: "青" },
    weak: { color: "lightblue", colorLabel: "水色" },
    catchphrase: {
      strong: "理性で世界を切り拓く知性派",
      weak: "穏やかで聞き上手な癒し型",
    },
    coreTraits: ["冷静", "分析的", "感情を内に秘める", "誠実"],
    loveTendency:
      "言葉より行動で示すタイプ。最初は距離を取るが、信頼すると深く長く愛する。",
  },
  cautious: {
    label: "慎重系",
    strong: { color: "green", colorLabel: "緑" },
    weak: { color: "yellowgreen", colorLabel: "黄緑" },
    catchphrase: {
      strong: "石橋を叩いて渡る堅実家",
      weak: "周囲をなごませる癒し系",
    },
    coreTraits: ["真面目", "計画的", "責任感が強い", "守りに入りやすい"],
    loveTendency:
      "じっくり時間をかけて相手を見極める恋。安心感を最優先するため、長続きする関係を築きやすい。",
  },
  freeSpirit: {
    label: "自由人系",
    strong: { color: "purple", colorLabel: "紫" },
    weak: { color: "navy", colorLabel: "紺" },
    catchphrase: {
      strong: "ミステリアスな求道者",
      weak: "静かな個性派の一匹狼",
    },
    coreTraits: ["独立心が強い", "理想主義", "束縛を嫌う", "感性が鋭い"],
    loveTendency:
      "自分の世界を理解してくれる相手を求める。重い関係よりもお互いを尊重する大人の恋を好む。",
  },
  hardWorker: {
    label: "努力家系",
    strong: { color: "brown", colorLabel: "茶" },
    weak: { color: "gray", colorLabel: "グレー" },
    catchphrase: {
      strong: "地に足のついた現実派リーダー",
      weak: "縁の下の力持ち系サポーター",
    },
    coreTraits: ["粘り強い", "現実的", "面倒見が良い", "我慢しがち"],
    loveTendency:
      "尽くす恋になりやすい。相手のために動くことに喜びを感じる反面、無理を抱え込みがち。",
  },
  moody: {
    label: "ムード系",
    strong: { color: "pink", colorLabel: "ピンク" },
    weak: { color: "yellow", colorLabel: "黄" },
    catchphrase: {
      strong: "感情豊かなロマンチスト",
      weak: "気まぐれで愛らしいムードメーカー",
    },
    coreTraits: ["感情の起伏が豊か", "共感力が高い", "ロマンチック", "気分屋"],
    loveTendency:
      "空気感やフィーリングを何より大切にする恋。心が動いたときの行動力は12オーラ随一。",
  },
};

const GROUP_ORDER: AuraGroup[] = [
  "eccentric",
  "cool",
  "cautious",
  "freeSpirit",
  "hardWorker",
  "moody",
];

const ZODIAC_ANIMALS = [
  "子",
  "丑",
  "寅",
  "卯",
  "辰",
  "巳",
  "午",
  "未",
  "申",
  "酉",
  "戌",
  "亥",
];

const WESTERN_ZODIAC: { name: string; from: [number, number]; to: [number, number] }[] = [
  { name: "山羊座", from: [12, 22], to: [1, 19] },
  { name: "水瓶座", from: [1, 20], to: [2, 18] },
  { name: "魚座", from: [2, 19], to: [3, 20] },
  { name: "牡羊座", from: [3, 21], to: [4, 19] },
  { name: "牡牛座", from: [4, 20], to: [5, 20] },
  { name: "双子座", from: [5, 21], to: [6, 21] },
  { name: "蟹座", from: [6, 22], to: [7, 22] },
  { name: "獅子座", from: [7, 23], to: [8, 22] },
  { name: "乙女座", from: [8, 23], to: [9, 22] },
  { name: "天秤座", from: [9, 23], to: [10, 23] },
  { name: "蠍座", from: [10, 24], to: [11, 22] },
  { name: "射手座", from: [11, 23], to: [12, 21] },
];

function parseDate(iso: string): { y: number; m: number; d: number } {
  const [y, m, d] = iso.split("-").map(Number);
  if (!y || !m || !d) {
    throw new Error(`Invalid birthDate: ${iso}`);
  }
  return { y, m, d };
}

function calcAge(iso: string, today = new Date()): number {
  const { y, m, d } = parseDate(iso);
  let age = today.getFullYear() - y;
  const beforeBirthday =
    today.getMonth() + 1 < m ||
    (today.getMonth() + 1 === m && today.getDate() < d);
  if (beforeBirthday) age -= 1;
  return age;
}

function zodiacAnimal(year: number): string {
  // 西暦 4年 = 子年
  const idx = ((year - 4) % 12 + 12) % 12;
  return ZODIAC_ANIMALS[idx];
}

function westernZodiac(month: number, day: number): string {
  for (const z of WESTERN_ZODIAC) {
    const [fm, fd] = z.from;
    const [tm, td] = z.to;
    if (fm === tm) {
      if (month === fm && day >= fd && day <= td) return z.name;
    } else if (fm < tm) {
      if (
        (month === fm && day >= fd) ||
        (month === tm && day <= td) ||
        (month > fm && month < tm)
      ) {
        return z.name;
      }
    } else {
      // 山羊座のように年をまたぐ
      if (
        (month === fm && day >= fd) ||
        (month === tm && day <= td)
      ) {
        return z.name;
      }
    }
  }
  return "山羊座";
}

// 決定論的だが見た目に複雑な擬似ハッシュ
function hash(...nums: number[]): number {
  let h = 2166136261;
  for (const n of nums) {
    h ^= n;
    h = Math.imul(h, 16777619);
  }
  return (h >>> 0);
}

export function determineAura(input: RenrekiInput): AuraProfile {
  const { y, m, d } = parseDate(input.birthDate);
  const genderBit = input.gender === "female" ? 1 : 0;

  // 6基本タイプ: 年・月・日と性別を混ぜたハッシュを6で割る
  const groupIdx = hash(y, m, d, genderBit) % 6;
  const group = GROUP_ORDER[groupIdx];

  // 強弱: 別シードのハッシュで2分割
  const polarityBit = hash(d, m, y, genderBit + 7) % 2;
  const polarity: Polarity = polarityBit === 0 ? "strong" : "weak";

  const def = GROUP_DEFINITIONS[group];
  const variant = polarity === "strong" ? def.strong : def.weak;

  return {
    group,
    groupLabel: def.label,
    polarity,
    color: variant.color,
    colorLabel: variant.colorLabel,
    catchphrase: def.catchphrase[polarity],
    coreTraits: def.coreTraits,
    loveTendency: def.loveTendency,
  };
}

function independenceNote(left: boolean): string {
  return left
    ? "10代で親元を離れて自立した経験により、本来の気質に「自分で人生を決める」強さが上書きされている。決断の早さと孤独耐性が同オーラの中でも際立つ。"
    : "10代を親元で過ごしたため、本来の気質がそのまま熟成されている。安心できる関係性の中で力を発揮しやすく、ホームに対する愛着が強い。";
}

function nurtureNote(spoiled: boolean): string {
  return spoiled
    ? "甘やかされて育った経験が、自己肯定感と「愛されて当然」という感覚を支えている。素直に甘えられる一方、思い通りにならない場面では子供っぽい一面が出やすい。"
    : "厳しめ・自立を促される環境で育ったため、他人に頼ることへのハードルが高い。責任感の裏で「もっと甘えたい」という願望が眠っている。";
}

export function runRenreki(input: RenrekiInput): RenrekiResult {
  const aura = determineAura(input);
  const { y, m, d } = parseDate(input.birthDate);
  return {
    aura,
    modifiers: {
      leftHomeAsTeen: input.leftHomeAsTeen,
      raisedSpoiled: input.raisedSpoiled,
      independenceNote: independenceNote(input.leftHomeAsTeen),
      nurtureNote: nurtureNote(input.raisedSpoiled),
    },
    basics: {
      gender: input.gender,
      birthDate: input.birthDate,
      age: calcAge(input.birthDate),
      zodiacAnimal: zodiacAnimal(y),
      westernZodiac: westernZodiac(m, d),
    },
  };
}
