"use client";

import { renderMarkdown } from "@/lib/markdown";
import type { RenrekiResult } from "@/lib/renreki";

interface Props {
  profile: RenrekiResult;
  report: string;
  onReset: () => void;
}

const COLOR_SWATCH: Record<string, string> = {
  red: "bg-red-500",
  orange: "bg-orange-400",
  blue: "bg-blue-600",
  lightblue: "bg-sky-300",
  green: "bg-emerald-500",
  yellowgreen: "bg-lime-400",
  purple: "bg-purple-600",
  navy: "bg-indigo-900",
  brown: "bg-amber-800",
  gray: "bg-slate-400",
  pink: "bg-pink-400",
  yellow: "bg-yellow-300",
};

export default function FortuneResult({ profile, report, onReset }: Props) {
  const a = profile.aura;
  const b = profile.basics;
  const m = profile.modifiers;
  const html = renderMarkdown(report);

  return (
    <div className="space-y-6">
      <section className="rounded-2xl bg-white/85 p-6 shadow-lg backdrop-blur">
        <header className="mb-4 flex items-center gap-3">
          <span
            className={`inline-block h-10 w-10 rounded-full shadow-inner ${
              COLOR_SWATCH[a.color] ?? "bg-slate-300"
            }`}
            aria-hidden
          />
          <div>
            <h2 className="text-xl font-bold text-rose-900">
              {a.colorLabel}オーラ
              <span className="ml-2 rounded bg-rose-100 px-2 py-0.5 text-xs text-rose-700">
                {a.groupLabel} / {a.polarity === "strong" ? "強" : "弱"}
              </span>
            </h2>
            <p className="text-sm text-slate-600">{a.catchphrase}</p>
          </div>
        </header>

        <dl className="grid grid-cols-1 gap-2 text-sm sm:grid-cols-2">
          <Row label="生年月日">
            {b.birthDate}（{b.age}歳）
          </Row>
          <Row label="干支 / 星座">
            {b.zodiacAnimal}年 ・ {b.westernZodiac}
          </Row>
          <Row label="10代で親元を離れた">
            {m.leftHomeAsTeen ? "はい" : "いいえ"}
          </Row>
          <Row label="甘やかされて育った">
            {m.raisedSpoiled ? "はい" : "いいえ"}
          </Row>
        </dl>
      </section>

      <article className="report-prose rounded-2xl bg-white/85 p-6 shadow-lg backdrop-blur">
        <div dangerouslySetInnerHTML={{ __html: html }} />
      </article>

      <div className="flex justify-center">
        <button
          type="button"
          onClick={onReset}
          className="rounded-xl border border-rose-300 bg-white px-6 py-2 text-sm font-semibold text-rose-700 shadow-sm hover:bg-rose-50"
        >
          もう一度鑑定する
        </button>
      </div>
    </div>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex justify-between border-b border-rose-50 py-1">
      <dt className="text-slate-500">{label}</dt>
      <dd className="font-medium text-slate-800">{children}</dd>
    </div>
  );
}
