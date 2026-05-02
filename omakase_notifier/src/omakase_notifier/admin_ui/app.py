"""Tkinter terminal-style admin UI.

Launches a single window with a scrollable output area and an input line
at the bottom. Looks and feels like a console.
"""

from __future__ import annotations

import logging
import queue
import sys
import tkinter as tk
from pathlib import Path
from tkinter import font as tkfont
from tkinter.scrolledtext import ScrolledText

from ..bootstrap import ensure_desktop_shortcut
from ..config import Config, default_config_path
from ..db import init_engine
from ..service import Service
from . import commands

BANNER = (
    " ____                  _                       \n"
    "/ __ \\ _ __ ___    __ _| | __ __ _ ___  ___    \n"
    "| |  | | '_ ` _ \\ / _` | |/ // _` / __|/ _ \\   \n"
    "| |__| | | | | | | (_| |   <| (_| \\__ \\  __/   \n"
    "\\____/|_| |_| |_|\\__,_|_|\\_\\\\__,_|___/\\___|   \n"
    "        Omakase Notifier — Admin Console\n"
    "        type 'help' for commands\n"
)


class TerminalApp:
    def __init__(self, root: tk.Tk, service: Service):
        self.root = root
        self.service = service
        self.history: list[str] = []
        self.history_index: int | None = None
        self._log_queue: "queue.Queue[str]" = queue.Queue()

        root.title("Omakase Notifier — Admin")
        root.configure(bg="#0b0f10")
        root.geometry("980x620")
        try:
            icon_path = Path(__file__).resolve().parent / "icon.ico"
            if icon_path.exists():
                root.iconbitmap(str(icon_path))
        except Exception:  # noqa: BLE001
            pass

        mono = tkfont.Font(family="Consolas", size=11)

        self.output = ScrolledText(
            root,
            wrap="word",
            bg="#0b0f10",
            fg="#cfe7d8",
            insertbackground="#cfe7d8",
            font=mono,
            relief="flat",
            borderwidth=0,
        )
        self.output.tag_configure("prompt", foreground="#7fd1b9")
        self.output.tag_configure("error", foreground="#ff7878")
        self.output.tag_configure("info", foreground="#88c0d0")
        self.output.tag_configure("banner", foreground="#7fd1b9")
        self.output.pack(fill="both", expand=True, padx=8, pady=(8, 0))
        self.output.configure(state="disabled")

        bottom = tk.Frame(root, bg="#0b0f10")
        bottom.pack(fill="x", padx=8, pady=8)
        tk.Label(
            bottom, text="omakase>", fg="#7fd1b9", bg="#0b0f10", font=mono
        ).pack(side="left")
        self.entry = tk.Entry(
            bottom,
            bg="#0b0f10",
            fg="#cfe7d8",
            insertbackground="#cfe7d8",
            font=mono,
            relief="flat",
        )
        self.entry.pack(side="left", fill="x", expand=True, padx=(6, 0))
        self.entry.bind("<Return>", self._on_enter)
        self.entry.bind("<Up>", self._on_history_up)
        self.entry.bind("<Down>", self._on_history_down)
        self.entry.focus_set()

        # Hook service log into the terminal.
        service.on_log = self._enqueue_log
        self._write(BANNER, tag="banner")
        self._write(commands.cmd_status(service, []), tag="info")

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(150, self._drain_log_queue)

    # -------- I/O --------
    def _write(self, text: str, tag: str | None = None) -> None:
        self.output.configure(state="normal")
        if tag:
            self.output.insert("end", text + "\n", tag)
        else:
            self.output.insert("end", text + "\n")
        self.output.see("end")
        self.output.configure(state="disabled")

    def _enqueue_log(self, msg: str) -> None:
        self._log_queue.put(msg)

    def _drain_log_queue(self) -> None:
        try:
            while True:
                msg = self._log_queue.get_nowait()
                self._write(f"[svc] {msg}", tag="info")
        except queue.Empty:
            pass
        self.root.after(200, self._drain_log_queue)

    # -------- Input --------
    def _on_enter(self, _evt) -> None:
        line = self.entry.get()
        self.entry.delete(0, "end")
        self._write(f"omakase> {line}", tag="prompt")
        if line.strip():
            self.history.append(line)
            self.history_index = None
        result = commands.execute(self.service, line)
        if result == "__QUIT__":
            self.root.after(50, self._on_close)
            return
        if result:
            tag = "error" if result.startswith("error:") else None
            self._write(result, tag=tag)

    def _on_history_up(self, _evt) -> str:
        if not self.history:
            return "break"
        if self.history_index is None:
            self.history_index = len(self.history) - 1
        else:
            self.history_index = max(0, self.history_index - 1)
        self.entry.delete(0, "end")
        self.entry.insert(0, self.history[self.history_index])
        return "break"

    def _on_history_down(self, _evt) -> str:
        if not self.history or self.history_index is None:
            return "break"
        self.history_index += 1
        if self.history_index >= len(self.history):
            self.history_index = None
            self.entry.delete(0, "end")
        else:
            self.entry.delete(0, "end")
            self.entry.insert(0, self.history[self.history_index])
        return "break"

    def _on_close(self) -> None:
        try:
            self.service.stop()
        finally:
            self.root.destroy()


def run() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    config = Config.load(default_config_path())
    init_engine(config)
    shortcut = ensure_desktop_shortcut()
    service = Service(config)
    service.start()

    root = tk.Tk()
    app = TerminalApp(root, service)
    if shortcut is not None:
        app._write(  # noqa: SLF001
            f"[setup] Desktop shortcut ready: {shortcut}", tag="info"
        )
    try:
        root.mainloop()
    finally:
        service.stop()


if __name__ == "__main__":
    sys.exit(run())
