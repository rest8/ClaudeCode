export type MbtiType =
  | "INTJ"
  | "INTP"
  | "ENTJ"
  | "ENTP"
  | "INFJ"
  | "INFP"
  | "ENFJ"
  | "ENFP"
  | "ISTJ"
  | "ISFJ"
  | "ESTJ"
  | "ESFJ"
  | "ISTP"
  | "ISFP"
  | "ESTP"
  | "ESFP";

export const MBTI_TYPES: MbtiType[] = [
  "INTJ", "INTP", "ENTJ", "ENTP",
  "INFJ", "INFP", "ENFJ", "ENFP",
  "ISTJ", "ISFJ", "ESTJ", "ESFJ",
  "ISTP", "ISFP", "ESTP", "ESFP",
];

export interface MbtiProfile {
  code: MbtiType;
  nickname: string;
  axis: string;
  loveSnapshot: string;
}

export const MBTI_PROFILES: Record<MbtiType, MbtiProfile> = {
  INTJ: {
    code: "INTJ",
    nickname: "建築家",
    axis: "I-N-T-J",
    loveSnapshot: "戦略的に長期の関係を設計する。表面的な恋には興味が薄い。",
  },
  INTP: {
    code: "INTP",
    nickname: "論理学者",
    axis: "I-N-T-P",
    loveSnapshot: "知的好奇心を共有できる相手に強く惹かれる。感情表現は不器用。",
  },
  ENTJ: {
    code: "ENTJ",
    nickname: "指揮官",
    axis: "E-N-T-J",
    loveSnapshot: "リードしたいタイプ。目標を共有できるパートナーを求める。",
  },
  ENTP: {
    code: "ENTP",
    nickname: "討論者",
    axis: "E-N-T-P",
    loveSnapshot: "刺激と議論を楽しむ。マンネリには弱いが、本気の相手には熱中する。",
  },
  INFJ: {
    code: "INFJ",
    nickname: "提唱者",
    axis: "I-N-F-J",
    loveSnapshot: "魂レベルの繋がりを求める。理想が高く、深い愛情を一人に注ぐ。",
  },
  INFP: {
    code: "INFP",
    nickname: "仲介者",
    axis: "I-N-F-P",
    loveSnapshot: "ロマンチストで内省的。自分の価値観を共有できる相手を待つ。",
  },
  ENFJ: {
    code: "ENFJ",
    nickname: "主人公",
    axis: "E-N-F-J",
    loveSnapshot: "相手の成長を支えるのが愛情表現。世話焼きで感情豊か。",
  },
  ENFP: {
    code: "ENFP",
    nickname: "運動家",
    axis: "E-N-F-P",
    loveSnapshot: "情熱的で自由。可能性を感じる相手に全力で飛び込む。",
  },
  ISTJ: {
    code: "ISTJ",
    nickname: "管理者",
    axis: "I-S-T-J",
    loveSnapshot: "誠実で着実。約束を守り、関係を一歩ずつ積み上げる安定型。",
  },
  ISFJ: {
    code: "ISFJ",
    nickname: "擁護者",
    axis: "I-S-F-J",
    loveSnapshot: "献身的で控えめ。相手の小さな変化に気づき、静かに支える。",
  },
  ESTJ: {
    code: "ESTJ",
    nickname: "幹部",
    axis: "E-S-T-J",
    loveSnapshot: "現実的で責任感が強い。家庭と仕事を両立させようとする努力家。",
  },
  ESFJ: {
    code: "ESFJ",
    nickname: "領事官",
    axis: "E-S-F-J",
    loveSnapshot: "愛情表現がストレート。みんなが幸せな関係を作るのが得意。",
  },
  ISTP: {
    code: "ISTP",
    nickname: "巨匠",
    axis: "I-S-T-P",
    loveSnapshot: "クールに見えて行動派。言葉より体験で愛情を示す。",
  },
  ISFP: {
    code: "ISFP",
    nickname: "冒険家",
    axis: "I-S-F-P",
    loveSnapshot: "繊細で芸術肌。深い感情を秘めつつ、感性で繋がる相手を求める。",
  },
  ESTP: {
    code: "ESTP",
    nickname: "起業家",
    axis: "E-S-T-P",
    loveSnapshot: "今この瞬間を全力で楽しむ。スリルと自由を共有できる相手が好み。",
  },
  ESFP: {
    code: "ESFP",
    nickname: "エンターテイナー",
    axis: "E-S-F-P",
    loveSnapshot: "明るく華やかに恋を彩る。一緒にいて楽しい人を本能的に選ぶ。",
  },
};
