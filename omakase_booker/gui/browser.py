"""Restaurant browser dialog for discovering and adding restaurants."""

import asyncio
import logging
import threading
import tkinter as tk
from tkinter import ttk

from ..config import Config, RestaurantInfo, RestaurantTarget
from ..omakase_client import OmakaseClient

logger = logging.getLogger(__name__)


class RestaurantBrowserDialog:
    """Dialog for browsing Omakase restaurants by area/genre and adding them as targets."""

    def __init__(self, parent: tk.Tk, config: Config):
        self.config = config
        self.parent = parent
        self._selected_restaurants: list[RestaurantTarget] = []
        self._browse_results: list[RestaurantInfo] = []
        self._areas: list[dict[str, str]] = []
        self._genres: list[dict[str, str]] = []
        self._client: OmakaseClient | None = None

        self._build_dialog()

    def _build_dialog(self):
        """Build the browser dialog window."""
        self.dialog = tk.Toplevel(self.parent)
        self.dialog.title("レストラン検索・追加")
        self.dialog.geometry("900x650")
        self.dialog.transient(self.parent)
        self.dialog.grab_set()

        main_frame = ttk.Frame(self.dialog, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Top: Search & Filter controls
        self._build_search_panel(main_frame)

        # Middle: Results area (left: list, right: detail)
        content = ttk.Frame(main_frame)
        content.pack(fill=tk.BOTH, expand=True, pady=(10, 0))

        self._build_results_panel(content)
        self._build_detail_panel(content)

        # Bottom: Action buttons
        self._build_action_panel(main_frame)

        # Status bar
        self.status_var = tk.StringVar(value="「読み込み」ボタンでエリア・ジャンルを取得してください")
        ttk.Label(
            main_frame, textvariable=self.status_var,
            font=("Yu Gothic UI", 9),
        ).pack(fill=tk.X, pady=(5, 0))

    def _build_search_panel(self, parent):
        """Build search and filter controls."""
        frame = ttk.LabelFrame(parent, text="検索・フィルタ", padding=10)
        frame.pack(fill=tk.X)

        # Row 1: Load button + Search
        row1 = ttk.Frame(frame)
        row1.pack(fill=tk.X, pady=(0, 5))

        ttk.Button(
            row1, text="読み込み",
            command=self._load_browse_urls,
            width=10,
        ).pack(side=tk.LEFT, padx=(0, 10))

        ttk.Label(row1, text="検索:").pack(side=tk.LEFT, padx=(0, 5))
        self.search_var = tk.StringVar()
        search_entry = ttk.Entry(row1, textvariable=self.search_var, width=30)
        search_entry.pack(side=tk.LEFT, padx=(0, 5))
        search_entry.bind("<Return>", lambda _: self._do_search())

        ttk.Button(
            row1, text="検索",
            command=self._do_search,
            width=8,
        ).pack(side=tk.LEFT)

        # Row 2: Area + Genre dropdowns
        row2 = ttk.Frame(frame)
        row2.pack(fill=tk.X)

        ttk.Label(row2, text="エリア:").pack(side=tk.LEFT, padx=(0, 5))
        self.area_var = tk.StringVar(value="-- 選択 --")
        self.area_combo = ttk.Combobox(
            row2, textvariable=self.area_var, state="readonly", width=20,
        )
        self.area_combo.pack(side=tk.LEFT, padx=(0, 15))
        self.area_combo.bind("<<ComboboxSelected>>", self._on_area_selected)

        ttk.Label(row2, text="ジャンル:").pack(side=tk.LEFT, padx=(0, 5))
        self.genre_var = tk.StringVar(value="-- 選択 --")
        self.genre_combo = ttk.Combobox(
            row2, textvariable=self.genre_var, state="readonly", width=20,
        )
        self.genre_combo.pack(side=tk.LEFT, padx=(0, 15))
        self.genre_combo.bind("<<ComboboxSelected>>", self._on_genre_selected)

        ttk.Button(
            row2, text="全ページ取得",
            command=self._browse_all_pages,
            width=12,
        ).pack(side=tk.LEFT)

    def _build_results_panel(self, parent):
        """Build the restaurant results list."""
        frame = ttk.LabelFrame(parent, text="レストラン一覧", padding=5)
        frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 5))

        # Treeview for results
        columns = ("name", "area", "genre", "price")
        self.results_tree = ttk.Treeview(
            frame, columns=columns, show="headings", height=15,
            selectmode="extended",
        )
        self.results_tree.heading("name", text="店名")
        self.results_tree.heading("area", text="エリア")
        self.results_tree.heading("genre", text="ジャンル")
        self.results_tree.heading("price", text="価格帯")

        self.results_tree.column("name", width=250)
        self.results_tree.column("area", width=100)
        self.results_tree.column("genre", width=100)
        self.results_tree.column("price", width=100)

        scrollbar = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=self.results_tree.yview)
        self.results_tree.configure(yscrollcommand=scrollbar.set)

        self.results_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.results_tree.bind("<<TreeviewSelect>>", self._on_result_select)

        # Result count
        self.result_count_var = tk.StringVar(value="0 件")
        ttk.Label(
            frame, textvariable=self.result_count_var,
            font=("Yu Gothic UI", 9),
        ).pack(fill=tk.X, pady=(3, 0))

    def _build_detail_panel(self, parent):
        """Build the restaurant detail panel."""
        frame = ttk.LabelFrame(parent, text="詳細", padding=10)
        frame.pack(side=tk.RIGHT, fill=tk.Y, padx=(5, 0))
        frame.configure(width=280)
        frame.pack_propagate(False)

        self.detail_name = tk.StringVar(value="---")
        ttk.Label(
            frame, textvariable=self.detail_name,
            font=("Yu Gothic UI", 12, "bold"),
            wraplength=250,
        ).pack(fill=tk.X, pady=(0, 5))

        self.detail_info = tk.StringVar(value="")
        ttk.Label(
            frame, textvariable=self.detail_info,
            font=("Yu Gothic UI", 9),
            wraplength=250,
            justify=tk.LEFT,
        ).pack(fill=tk.X, pady=(0, 10))

        self.detail_desc = tk.StringVar(value="")
        ttk.Label(
            frame, textvariable=self.detail_desc,
            font=("Yu Gothic UI", 9),
            wraplength=250,
            justify=tk.LEFT,
        ).pack(fill=tk.X, pady=(0, 10))

        # Booking settings for selected restaurant
        settings_frame = ttk.LabelFrame(frame, text="予約設定", padding=5)
        settings_frame.pack(fill=tk.X, pady=(0, 10))

        r1 = ttk.Frame(settings_frame)
        r1.pack(fill=tk.X, pady=2)
        ttk.Label(r1, text="人数:").pack(side=tk.LEFT)
        self.party_size_var = tk.IntVar(value=2)
        ttk.Spinbox(
            r1, from_=1, to=10, textvariable=self.party_size_var, width=5,
        ).pack(side=tk.LEFT, padx=(5, 0))

        r2 = ttk.Frame(settings_frame)
        r2.pack(fill=tk.X, pady=2)
        ttk.Label(r2, text="モード:").pack(side=tk.LEFT)
        self.mode_var = tk.StringVar(value="first_come")
        ttk.Radiobutton(r2, text="先着", variable=self.mode_var, value="first_come").pack(side=tk.LEFT, padx=5)
        ttk.Radiobutton(r2, text="抽選", variable=self.mode_var, value="lottery").pack(side=tk.LEFT)

        r3 = ttk.Frame(settings_frame)
        r3.pack(fill=tk.X, pady=2)
        ttk.Label(r3, text="時間帯:").pack(side=tk.LEFT)
        self.times_var = tk.StringVar(value="18:00, 19:00, 20:00")
        ttk.Entry(r3, textvariable=self.times_var, width=20).pack(side=tk.LEFT, padx=(5, 0))

        # Add button (prominent)
        ttk.Button(
            frame, text="予約対象に追加 →",
            command=self._add_selected,
        ).pack(fill=tk.X, pady=(10, 0))

    def _build_action_panel(self, parent):
        """Build bottom action buttons."""
        frame = ttk.Frame(parent)
        frame.pack(fill=tk.X, pady=(10, 0))

        ttk.Button(
            frame, text="選択を一括追加",
            command=self._add_all_selected,
        ).pack(side=tk.LEFT, padx=(0, 10))

        self.added_count_var = tk.StringVar(value="追加済み: 0 件")
        ttk.Label(
            frame, textvariable=self.added_count_var,
            font=("Yu Gothic UI", 10, "bold"),
        ).pack(side=tk.LEFT)

        ttk.Button(
            frame, text="完了",
            command=self._on_done,
            width=10,
        ).pack(side=tk.RIGHT)

    # ── Background Tasks ──────────────────────────────────────

    def _run_async(self, coro, callback=None):
        """Run an async function in a background thread."""
        def worker():
            loop = asyncio.new_event_loop()
            try:
                result = loop.run_until_complete(coro)
                if callback:
                    self.dialog.after(0, lambda: callback(result))
            except Exception as e:
                logger.exception("Browser async error")
                self.dialog.after(0, lambda: self._set_status(f"エラー: {e}"))
            finally:
                loop.close()

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()

    async def _get_client(self) -> OmakaseClient:
        """Get or create the browser client."""
        if self._client is None:
            self._client = OmakaseClient(self.config)
            await self._client.start()
        return self._client

    async def _close_client(self):
        if self._client:
            await self._client.close()
            self._client = None

    # ── Event Handlers ────────────────────────────────────────

    def _load_browse_urls(self):
        """Load area and genre categories from Omakase."""
        self._set_status("サイトからエリア・ジャンルを取得中...")

        async def do_discover():
            client = await self._get_client()
            return await client.discover_browse_urls()

        def on_result(result):
            self._areas = result.get("areas", [])
            self._genres = result.get("genres", [])

            area_names = ["-- 選択 --"] + [a["name"] for a in self._areas]
            genre_names = ["-- 選択 --"] + [g["name"] for g in self._genres]

            self.area_combo["values"] = area_names
            self.genre_combo["values"] = genre_names

            self._set_status(
                f"取得完了: {len(self._areas)} エリア, {len(self._genres)} ジャンル"
            )

        self._run_async(do_discover(), on_result)

    def _on_area_selected(self, _event=None):
        """Browse restaurants in selected area."""
        idx = self.area_combo.current()
        if idx <= 0:  # "-- 選択 --"
            return
        area = self._areas[idx - 1]
        self._set_status(f"「{area['name']}」のレストランを取得中...")

        async def do_browse():
            client = await self._get_client()
            return await client.browse_restaurants(area["url"])

        def on_result(restaurants):
            self._update_results(restaurants)
            self._set_status(f"「{area['name']}」: {len(restaurants)} 件")

        self._run_async(do_browse(), on_result)

    def _on_genre_selected(self, _event=None):
        """Browse restaurants of selected genre."""
        idx = self.genre_combo.current()
        if idx <= 0:
            return
        genre = self._genres[idx - 1]
        self._set_status(f"「{genre['name']}」のレストランを取得中...")

        async def do_browse():
            client = await self._get_client()
            return await client.browse_restaurants(genre["url"])

        def on_result(restaurants):
            self._update_results(restaurants)
            self._set_status(f"「{genre['name']}」: {len(restaurants)} 件")

        self._run_async(do_browse(), on_result)

    def _browse_all_pages(self):
        """Browse all pages of current selection."""
        # Determine which URL to use
        area_idx = self.area_combo.current()
        genre_idx = self.genre_combo.current()

        if area_idx > 0:
            target = self._areas[area_idx - 1]
        elif genre_idx > 0:
            target = self._genres[genre_idx - 1]
        else:
            self._set_status("エリアまたはジャンルを選択してください")
            return

        self._set_status(f"「{target['name']}」の全ページを取得中...")

        async def do_browse_all():
            client = await self._get_client()
            return await client.browse_restaurants_all_pages(target["url"])

        def on_result(restaurants):
            self._update_results(restaurants)
            self._set_status(f"「{target['name']}」全ページ: {len(restaurants)} 件")

        self._run_async(do_browse_all(), on_result)

    def _do_search(self):
        """Search restaurants by keyword."""
        query = self.search_var.get().strip()
        if not query:
            return
        self._set_status(f"「{query}」を検索中...")

        async def do_search():
            client = await self._get_client()
            return await client.search_restaurants(query)

        def on_result(restaurants):
            self._update_results(restaurants)
            self._set_status(f"「{query}」: {len(restaurants)} 件")

        self._run_async(do_search(), on_result)

    def _on_result_select(self, _event=None):
        """Show detail for selected restaurant."""
        sel = self.results_tree.selection()
        if not sel:
            return
        item = self.results_tree.item(sel[0])
        idx = self.results_tree.index(sel[0])
        if idx < len(self._browse_results):
            info = self._browse_results[idx]
            self.detail_name.set(info.name)
            detail_lines = []
            if info.area:
                detail_lines.append(f"エリア: {info.area}")
            if info.genre:
                detail_lines.append(f"ジャンル: {info.genre}")
            if info.price_range:
                detail_lines.append(f"価格帯: {info.price_range}")
            if info.rating:
                detail_lines.append(f"評価: {info.rating}")
            detail_lines.append(f"URL: {info.url}")
            self.detail_info.set("\n".join(detail_lines))
            self.detail_desc.set(info.description or "")

    def _add_selected(self):
        """Add the currently viewed restaurant to targets."""
        sel = self.results_tree.selection()
        if not sel:
            self._set_status("レストランを選択してください")
            return

        idx = self.results_tree.index(sel[0])
        if idx >= len(self._browse_results):
            return

        info = self._browse_results[idx]
        times = [t.strip() for t in self.times_var.get().split(",") if t.strip()]

        target = RestaurantTarget(
            name=info.name,
            omakase_url=info.url,
            party_size=self.party_size_var.get(),
            preferred_times=times or ["18:00", "19:00", "20:00"],
            booking_mode=self.mode_var.get(),
            watch_cancellations=True,
        )

        # Avoid duplicates
        if not any(t.omakase_url == target.omakase_url for t in self._selected_restaurants):
            self._selected_restaurants.append(target)
            self.added_count_var.set(f"追加済み: {len(self._selected_restaurants)} 件")
            self._set_status(f"「{info.name}」を追加しました")
        else:
            self._set_status(f"「{info.name}」は既に追加済みです")

    def _add_all_selected(self):
        """Add all selected restaurants in the tree to targets."""
        selections = self.results_tree.selection()
        if not selections:
            self._set_status("レストランを選択してください")
            return

        times = [t.strip() for t in self.times_var.get().split(",") if t.strip()]
        added = 0

        for sel_id in selections:
            idx = self.results_tree.index(sel_id)
            if idx >= len(self._browse_results):
                continue
            info = self._browse_results[idx]
            if any(t.omakase_url == info.url for t in self._selected_restaurants):
                continue

            target = RestaurantTarget(
                name=info.name,
                omakase_url=info.url,
                party_size=self.party_size_var.get(),
                preferred_times=times or ["18:00", "19:00", "20:00"],
                booking_mode=self.mode_var.get(),
                watch_cancellations=True,
            )
            self._selected_restaurants.append(target)
            added += 1

        self.added_count_var.set(f"追加済み: {len(self._selected_restaurants)} 件")
        self._set_status(f"{added} 件追加しました")

    def _on_done(self):
        """Close the dialog and clean up."""
        # Close client in background
        if self._client:
            async def cleanup():
                await self._close_client()
            self._run_async(cleanup())

        self.dialog.destroy()

    # ── Helpers ────────────────────────────────────────────────

    def _update_results(self, restaurants: list[RestaurantInfo]):
        """Update the results treeview."""
        self._browse_results = restaurants
        self.results_tree.delete(*self.results_tree.get_children())

        for r in restaurants:
            self.results_tree.insert("", tk.END, values=(
                r.name, r.area, r.genre, r.price_range,
            ))

        self.result_count_var.set(f"{len(restaurants)} 件")

    def _set_status(self, text: str):
        """Update status bar text."""
        self.status_var.set(text)

    def get_selected_restaurants(self) -> list[RestaurantTarget]:
        """Get the list of restaurants selected by the user."""
        return self._selected_restaurants
