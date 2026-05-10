"use client";

import { useState } from "react";
import FortuneForm, { FortuneFormValues } from "@/components/FortuneForm";
import FortuneResult from "@/components/FortuneResult";
import type { RenrekiResult } from "@/lib/renreki";

interface ApiSuccess {
  profile: RenrekiResult;
  report: string;
}

export default function HomePage() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [data, setData] = useState<ApiSuccess | null>(null);

  const handleSubmit = async (values: FortuneFormValues) => {
    setLoading(true);
    setError(null);
    setData(null);
    try {
      const res = await fetch("/api/fortune", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(values),
      });
      const json = await res.json();
      if (!res.ok) {
        setError(json.error ?? "予期せぬエラーが発生しました。");
        return;
      }
      setData(json as ApiSuccess);
    } catch (err) {
      setError(err instanceof Error ? err.message : "通信エラーが発生しました。");
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="mx-auto max-w-2xl px-4 py-10 sm:py-14">
      <header className="mb-8 text-center">
        <p className="text-xs tracking-widest text-rose-500">RENREKI × MBTI</p>
        <h1 className="mt-1 font-serif text-3xl font-bold text-rose-900 sm:text-4xl">
          恋暦 × MBTI 占術
        </h1>
        <p className="mt-2 text-sm text-slate-600">
          恋暦占術の世界観と MBTI を融合させた、あなただけのレポートを生成します。
        </p>
      </header>

      {!data && (
        <FortuneForm onSubmit={handleSubmit} loading={loading} />
      )}

      {error && (
        <p className="mt-6 rounded-xl bg-rose-100 p-4 text-sm text-rose-900 shadow">
          {error}
        </p>
      )}

      {data && (
        <FortuneResult
          profile={data.profile}
          report={data.report}
          onReset={() => {
            setData(null);
            setError(null);
          }}
        />
      )}

      <footer className="mt-12 text-center text-xs text-slate-500">
        <p>
          ※ 本サイトは恋暦占術 (
          <a
            href="https://renreki.com/"
            target="_blank"
            rel="noreferrer noopener"
            className="underline"
          >
            renreki.com
          </a>
          ) の世界観を参考にしたファンメイドのオリジナル占術であり、本家の鑑定結果とは一致しません。
        </p>
      </footer>
    </main>
  );
}
