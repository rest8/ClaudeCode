"""GUI Launcher for iFOREX Trading Bot.

Provides a tkinter-based window for selecting a trading strategy
and starting/stopping the bot.
"""

import threading
import tkinter as tk
from tkinter import ttk, messagebox

from loguru import logger

from iforex_trader.config import Config
from iforex_trader.bot import TradingBot
from iforex_trader.strategies.registry import STRATEGY_REGISTRY, get_strategy_by_name


class LauncherApp:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("iFOREX 自動売買システム")
        self.root.geometry("520x480")
        self.root.resizable(False, False)

        self.bot: TradingBot | None = None
        self.bot_thread: threading.Thread | None = None

        self._build_ui()

    def _build_ui(self) -> None:
        # Title
        title = tk.Label(
            self.root, text="iFOREX 自動売買システム",
            font=("Meiryo UI", 16, "bold"),
        )
        title.pack(pady=(20, 10))

        # Strategy selection frame
        frame = tk.LabelFrame(
            self.root, text="売買ロジックを選択",
            font=("Meiryo UI", 11), padx=15, pady=10,
        )
        frame.pack(padx=20, pady=10, fill="x")

        self.selected_strategy = tk.StringVar()

        for i, entry in enumerate(STRATEGY_REGISTRY):
            rb = tk.Radiobutton(
                frame,
                text=f'{entry["name"]}',
                variable=self.selected_strategy,
                value=entry["name"],
                font=("Meiryo UI", 10),
                anchor="w",
                command=self._on_strategy_select,
            )
            rb.pack(fill="x", pady=2)

            desc = tk.Label(
                frame, text=f'    {entry["description"]}',
                font=("Meiryo UI", 9), fg="#666666", anchor="w",
            )
            desc.pack(fill="x")

        # Select first by default
        if STRATEGY_REGISTRY:
            self.selected_strategy.set(STRATEGY_REGISTRY[0]["name"])

        # Settings display
        settings_frame = tk.LabelFrame(
            self.root, text="設定",
            font=("Meiryo UI", 11), padx=15, pady=10,
        )
        settings_frame.pack(padx=20, pady=10, fill="x")

        config = Config()
        settings_text = (
            f"取引間隔: {config.trade_interval_seconds}秒    "
            f"ロットサイズ: {config.default_lot_size}    "
            f"ヘッドレス: {'ON' if config.headless else 'OFF'}"
        )
        tk.Label(
            settings_frame, text=settings_text,
            font=("Meiryo UI", 9), fg="#333333",
        ).pack()
        tk.Label(
            settings_frame,
            text="※ .env ファイルで変更可能",
            font=("Meiryo UI", 8), fg="#999999",
        ).pack()

        # Buttons
        btn_frame = tk.Frame(self.root)
        btn_frame.pack(pady=15)

        self.start_btn = tk.Button(
            btn_frame, text="▶  開始",
            font=("Meiryo UI", 12, "bold"),
            width=12, bg="#4CAF50", fg="white",
            command=self._on_start,
        )
        self.start_btn.pack(side="left", padx=10)

        self.stop_btn = tk.Button(
            btn_frame, text="■  停止",
            font=("Meiryo UI", 12, "bold"),
            width=12, bg="#f44336", fg="white",
            command=self._on_stop,
            state="disabled",
        )
        self.stop_btn.pack(side="left", padx=10)

        # Status bar
        self.status_var = tk.StringVar(value="停止中")
        status_bar = tk.Label(
            self.root, textvariable=self.status_var,
            font=("Meiryo UI", 10), fg="#555555",
            relief="sunken", anchor="w", padx=10,
        )
        status_bar.pack(side="bottom", fill="x")

    def _on_strategy_select(self) -> None:
        name = self.selected_strategy.get()
        logger.debug("Strategy selected: {}", name)

    def _on_start(self) -> None:
        name = self.selected_strategy.get()
        if not name:
            messagebox.showwarning("警告", "売買ロジックを選択してください。")
            return

        config = Config()
        if not config.email or not config.password:
            messagebox.showerror(
                "エラー",
                ".env ファイルに iFOREX のメールアドレスとパスワードを設定してください。",
            )
            return

        try:
            strategy = get_strategy_by_name(name)
        except ValueError as e:
            messagebox.showerror("エラー", str(e))
            return

        self.bot = TradingBot(config=config, strategy=strategy)

        self.start_btn.config(state="disabled")
        self.stop_btn.config(state="normal")
        self.status_var.set(f"稼働中 — {name}")

        self.bot_thread = threading.Thread(target=self._run_bot, daemon=True)
        self.bot_thread.start()

    def _run_bot(self) -> None:
        try:
            self.bot.start()
        except Exception as e:
            logger.error("Bot crashed: {}", e)
            self.root.after(0, lambda: self._on_bot_stopped(error=str(e)))
            return
        self.root.after(0, lambda: self._on_bot_stopped())

    def _on_bot_stopped(self, error: str | None = None) -> None:
        self.start_btn.config(state="normal")
        self.stop_btn.config(state="disabled")
        self.status_var.set("停止中")
        if error:
            messagebox.showerror("エラー", f"ボットがエラーで停止しました:\n{error}")

    def _on_stop(self) -> None:
        if self.bot:
            self.bot.stop()
        self.start_btn.config(state="normal")
        self.stop_btn.config(state="disabled")
        self.status_var.set("停止中")

    def run(self) -> None:
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.mainloop()

    def _on_close(self) -> None:
        if self.bot and self.bot._running:
            if not messagebox.askyesno("確認", "ボットが稼働中です。終了しますか？"):
                return
            self.bot.stop()
        self.root.destroy()


def main():
    app = LauncherApp()
    app.run()


if __name__ == "__main__":
    main()
