"use client";

import { useState } from "react";
import { MBTI_PROFILES, MBTI_TYPES, MbtiType } from "@/lib/mbti";

export interface FortuneFormValues {
  gender: "male" | "female";
  birthDate: string;
  leftHomeAsTeen: boolean;
  raisedSpoiled: boolean;
  mbti: MbtiType;
}

interface Props {
  onSubmit: (values: FortuneFormValues) => void;
  loading: boolean;
}

const todayISO = () => new Date().toISOString().slice(0, 10);

export default function FortuneForm({ onSubmit, loading }: Props) {
  const [gender, setGender] = useState<"male" | "female">("female");
  const [birthDate, setBirthDate] = useState("1995-06-15");
  const [leftHomeAsTeen, setLeftHomeAsTeen] = useState(false);
  const [raisedSpoiled, setRaisedSpoiled] = useState(false);
  const [mbti, setMbti] = useState<MbtiType>("INFP");
  const [error, setError] = useState<string | null>(null);

  const handle = (e: React.FormEvent) => {
    e.preventDefault();
    if (!birthDate) {
      setError("生年月日を入力してください。");
      return;
    }
    if (birthDate > todayISO()) {
      setError("生年月日は本日以前の日付を入力してください。");
      return;
    }
    setError(null);
    onSubmit({ gender, birthDate, leftHomeAsTeen, raisedSpoiled, mbti });
  };

  return (
    <form
      onSubmit={handle}
      className="space-y-6 rounded-2xl bg-white/80 p-6 shadow-lg backdrop-blur"
    >
      <fieldset className="space-y-2">
        <legend className="text-sm font-semibold text-rose-900">① 性別</legend>
        <div className="flex gap-3">
          {[
            { v: "female", label: "女性" },
            { v: "male", label: "男性" },
          ].map((o) => (
            <label
              key={o.v}
              className={`flex-1 cursor-pointer rounded-xl border px-4 py-3 text-center text-sm transition ${
                gender === o.v
                  ? "border-rose-400 bg-rose-100 text-rose-900"
                  : "border-slate-200 bg-white hover:bg-rose-50"
              }`}
            >
              <input
                type="radio"
                name="gender"
                value={o.v}
                checked={gender === o.v}
                onChange={() => setGender(o.v as "male" | "female")}
                className="sr-only"
              />
              {o.label}
            </label>
          ))}
        </div>
      </fieldset>

      <div className="space-y-2">
        <label className="text-sm font-semibold text-rose-900" htmlFor="birthDate">
          ② 生年月日
        </label>
        <input
          id="birthDate"
          type="date"
          value={birthDate}
          max={todayISO()}
          min="1900-01-01"
          onChange={(e) => setBirthDate(e.target.value)}
          className="w-full rounded-xl border border-slate-200 bg-white px-4 py-3 text-base focus:border-rose-400 focus:outline-none"
        />
      </div>

      <fieldset className="space-y-2">
        <legend className="text-sm font-semibold text-rose-900">
          ③ 10代で親元を離れて暮らしたか
        </legend>
        <BoolToggle value={leftHomeAsTeen} onChange={setLeftHomeAsTeen} />
      </fieldset>

      <fieldset className="space-y-2">
        <legend className="text-sm font-semibold text-rose-900">
          ④ どちらかといえば甘やかされて育った
        </legend>
        <BoolToggle value={raisedSpoiled} onChange={setRaisedSpoiled} />
      </fieldset>

      <div className="space-y-2">
        <label className="text-sm font-semibold text-rose-900" htmlFor="mbti">
          ⑤ MBTI
        </label>
        <select
          id="mbti"
          value={mbti}
          onChange={(e) => setMbti(e.target.value as MbtiType)}
          className="w-full rounded-xl border border-slate-200 bg-white px-4 py-3 text-base focus:border-rose-400 focus:outline-none"
        >
          {MBTI_TYPES.map((t) => (
            <option key={t} value={t}>
              {t} — {MBTI_PROFILES[t].nickname}
            </option>
          ))}
        </select>
      </div>

      {error && (
        <p className="rounded-md bg-rose-100 px-3 py-2 text-sm text-rose-800">{error}</p>
      )}

      <button
        type="submit"
        disabled={loading}
        className="w-full rounded-xl bg-gradient-to-r from-rose-500 via-pink-500 to-violet-500 px-6 py-3 text-base font-semibold text-white shadow-md transition hover:opacity-95 disabled:opacity-60"
      >
        {loading ? "占術中…" : "鑑定する"}
      </button>
    </form>
  );
}

function BoolToggle({
  value,
  onChange,
}: {
  value: boolean;
  onChange: (b: boolean) => void;
}) {
  return (
    <div className="flex gap-3">
      {[
        { v: true, label: "はい" },
        { v: false, label: "いいえ" },
      ].map((o) => (
        <button
          key={String(o.v)}
          type="button"
          onClick={() => onChange(o.v)}
          className={`flex-1 rounded-xl border px-4 py-3 text-sm transition ${
            value === o.v
              ? "border-rose-400 bg-rose-100 text-rose-900"
              : "border-slate-200 bg-white hover:bg-rose-50"
          }`}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}
