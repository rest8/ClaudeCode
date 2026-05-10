import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: [
          "Hiragino Sans",
          "Hiragino Kaku Gothic ProN",
          "Noto Sans JP",
          "Yu Gothic",
          "system-ui",
          "sans-serif",
        ],
        serif: [
          "Hiragino Mincho ProN",
          "Yu Mincho",
          "Noto Serif JP",
          "serif",
        ],
      },
    },
  },
  plugins: [],
};

export default config;
