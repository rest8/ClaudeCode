import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "恋暦 × MBTI 占術 — 縁 (えにし)",
  description:
    "恋暦占術の世界観と MBTI を融合させた、あなただけの恋愛・人間関係レポートを生成します。",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="ja">
      <body className="min-h-screen bg-gradient-to-br from-rose-50 via-amber-50 to-violet-50 text-slate-800 antialiased">
        {children}
      </body>
    </html>
  );
}
