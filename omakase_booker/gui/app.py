"""Main GUI application window with calendar and booking controls."""

import asyncio
import logging
import threading
import tkinter as tk
from datetime import date, datetime, timedelta
from tkinter import messagebox

import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from tkcalendar import Calendar

from ..config import Config, RestaurantTarget
from ..calendar_checker import get_events_for_range, create_booking_event
from ..approval import request_approval, APPROVED, REJECTED, PENDING
from ..omakase_client import OmakaseClient, OmakaseBookingError
from .browser import RestaurantBrowserDialog

logger = logging.getLogger(__name__)

# Colors for calendar markers
COLOR_GCAL_EVENT = "#4285f4"     # Google blue - existing calendar events
COLOR_CANDIDATE = "#fbbc04"      # Yellow - selected candidate dates
COLOR_BOOKED = "#34a853"         # Green - successfully booked


class OmakaseApp:
    """Main GUI application."""

    def __init__(self, config: Config):
        self.config = config
        self._candidate_dates: set[date] = set()
        self._gcal_events: list[dict] = []
        self._booked_dates: set[date] = set()
        self._booked_keys: set[tuple[str, str, str]] = set()  # (url, date, time)
        self._booking_thread: threading.Thread | None = None
        self._stop_event = threading.Event()

        self._build_ui()
        self._load_restaurants()
        self._sync_calendar()

    def _build_ui(self):
        """Build the main application window."""
        self.root = ttk.Window(
            title="Omakase Auto-Booker",
            themename="cosmo",
            size=(1000, 700),
            resizable=(True, True),
        )
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # Main container
        main_frame = ttk.Frame(self.root, padding=10)
        main_frame.pack(fill=BOTH, expand=True)

        # Left panel: Calendar
        left_frame = ttk.LabelFrame(main_frame, text="カレンダー", padding=10)
        left_frame.pack(side=LEFT, fill=BOTH, expand=True, padx=(0, 5))

        self._build_calendar(left_frame)

        # Right panel: Controls
        right_frame = ttk.Frame(main_frame)
        right_frame.pack(side=RIGHT, fill=BOTH, expand=False, padx=(5, 0))

        self._build_restaurant_panel(right_frame)
        self._build_candidate_panel(right_frame)
        self._build_action_panel(right_frame)
        self._build_log_panel(right_frame)

    def _build_calendar(self, parent):
        """Build the calendar widget with Google Calendar overlay."""
        today = date.today()

        self.calendar = Calendar(
            parent,
            selectmode="day",
            year=today.year,
            month=today.month,
            day=today.day,
            locale="ja_JP",
            font=("Yu Gothic UI", 10),
            showweeknumbers=False,
            firstweekday="monday",
            borderwidth=0,
            cursor="hand2",
        )
        self.calendar.pack(fill=BOTH, expand=True, pady=(0, 10))

        # Bind click to toggle candidate date
        self.calendar.bind("<<CalendarSelected>>", self._on_date_click)
        # Bind month change to refresh calendar events
        self.calendar.bind("<<CalendarMonthChanged>>", self._on_month_changed)

        # Legend
        legend_frame = ttk.Frame(parent)
        legend_frame.pack(fill=X)

        for color, label in [
            (COLOR_GCAL_EVENT, "Google Calendar"),
            (COLOR_CANDIDATE, "予約候補日"),
            (COLOR_BOOKED, "予約済み"),
        ]:
            dot = tk.Canvas(legend_frame, width=12, height=12, highlightthickness=0)
            dot.create_oval(2, 2, 10, 10, fill=color, outline=color)
            dot.pack(side=LEFT, padx=(10, 2))
            ttk.Label(legend_frame, text=label, font=("Yu Gothic UI", 9)).pack(side=LEFT, padx=(0, 10))

        # Sync button
        ttk.Button(
            parent,
            text="カレンダー同期",
            command=self._sync_calendar,
            bootstyle="info-outline",
        ).pack(fill=X, pady=(10, 0))

    def _build_restaurant_panel(self, parent):
        """Build the restaurant selection panel."""
        frame = ttk.LabelFrame(parent, text="レストラン", padding=10, width=350)
        frame.pack(fill=X, pady=(0, 10))
        frame.pack_propagate(False)
        frame.configure(height=220)

        self.restaurant_listbox = tk.Listbox(
            frame,
            font=("Yu Gothic UI", 10),
            selectmode=tk.EXTENDED,
            height=5,
        )
        self.restaurant_listbox.pack(fill=BOTH, expand=True)
        self.restaurant_listbox.bind("<<ListboxSelect>>", self._on_restaurant_select)

        btn_row = ttk.Frame(frame)
        btn_row.pack(fill=X, pady=(5, 0))

        ttk.Button(
            btn_row, text="検索して追加",
            command=self._open_browser,
            bootstyle="info-outline",
            width=12,
        ).pack(side=LEFT, padx=(0, 5))

        ttk.Button(
            btn_row, text="削除",
            command=self._remove_restaurant,
            bootstyle="danger-outline",
            width=6,
        ).pack(side=LEFT)

        # Continuous mode toggle
        self.continuous_var = tk.BooleanVar(value=self.config.continuous_mode)
        ttk.Checkbutton(
            btn_row, text="常時監視",
            variable=self.continuous_var,
            bootstyle="round-toggle",
        ).pack(side=RIGHT)

    def _build_candidate_panel(self, parent):
        """Build the candidate dates display panel."""
        frame = ttk.LabelFrame(parent, text="予約候補日", padding=10, width=350)
        frame.pack(fill=X, pady=(0, 10))
        frame.pack_propagate(False)
        frame.configure(height=120)

        self.candidate_listbox = tk.Listbox(
            frame,
            font=("Yu Gothic UI", 10),
            height=4,
        )
        self.candidate_listbox.pack(fill=BOTH, expand=True, side=LEFT)

        btn_frame = ttk.Frame(frame)
        btn_frame.pack(side=RIGHT, fill=Y, padx=(5, 0))

        ttk.Button(
            btn_frame,
            text="削除",
            command=self._remove_candidate,
            bootstyle="danger-outline",
            width=6,
        ).pack(pady=(0, 5))

        ttk.Button(
            btn_frame,
            text="全削除",
            command=self._clear_candidates,
            bootstyle="danger-outline",
            width=6,
        ).pack()

    def _build_action_panel(self, parent):
        """Build the booking action panel."""
        frame = ttk.LabelFrame(parent, text="予約実行", padding=10, width=350)
        frame.pack(fill=X, pady=(0, 10))

        self.start_btn = ttk.Button(
            frame,
            text="予約開始",
            command=self._start_booking,
            bootstyle="success",
            width=20,
        )
        self.start_btn.pack(fill=X, pady=(0, 5))

        self.stop_btn = ttk.Button(
            frame,
            text="停止",
            command=self._stop_booking,
            bootstyle="danger",
            width=20,
            state=DISABLED,
        )
        self.stop_btn.pack(fill=X, pady=(0, 5))

        # Status label
        self.status_var = tk.StringVar(value="待機中")
        self.status_label = ttk.Label(
            frame,
            textvariable=self.status_var,
            font=("Yu Gothic UI", 10),
            bootstyle="info",
        )
        self.status_label.pack(fill=X)

        # Progress bar
        self.progress = ttk.Progressbar(
            frame,
            mode="indeterminate",
            bootstyle="info",
        )
        self.progress.pack(fill=X, pady=(5, 0))

    def _build_log_panel(self, parent):
        """Build the log output panel."""
        frame = ttk.LabelFrame(parent, text="ログ", padding=10, width=350)
        frame.pack(fill=BOTH, expand=True)

        self.log_text = tk.Text(
            frame,
            font=("Consolas", 9),
            height=8,
            wrap=tk.WORD,
            state=tk.DISABLED,
            bg="#1e1e1e",
            fg="#d4d4d4",
        )
        self.log_text.pack(fill=BOTH, expand=True)

        scrollbar = ttk.Scrollbar(self.log_text, command=self.log_text.yview)
        scrollbar.pack(side=RIGHT, fill=Y)
        self.log_text.configure(yscrollcommand=scrollbar.set)

    # ── Data / Logic ──────────────────────────────────────────

    def _load_restaurants(self):
        """Populate the restaurant listbox from config."""
        self.restaurant_listbox.delete(0, tk.END)
        for r in self.config.target_restaurants:
            mode = "抽選" if r.booking_mode == "lottery" else "先着"
            self.restaurant_listbox.insert(
                tk.END,
                f"{r.name}  ({r.party_size}名, {mode})",
            )
        if self.config.target_restaurants:
            self.restaurant_listbox.selection_set(0)

    def _get_selected_restaurant(self) -> RestaurantTarget | None:
        """Get the currently selected restaurant."""
        sel = self.restaurant_listbox.curselection()
        if not sel:
            return None
        idx = sel[0]
        if idx < len(self.config.target_restaurants):
            return self.config.target_restaurants[idx]
        return None

    def _sync_calendar(self, *_args):
        """Fetch Google Calendar events and update the calendar display."""
        self._log("Google カレンダーを同期中...")
        try:
            today = date.today()
            end = today + timedelta(days=90)
            self._gcal_events = get_events_for_range(self.config, today, end)
            self._refresh_calendar_tags()
            self._log(f"同期完了: {len(self._gcal_events)} 件のイベント")
        except Exception as e:
            self._log(f"カレンダー同期エラー: {e}")
            logger.exception("Calendar sync failed")

    def _refresh_calendar_tags(self):
        """Update calendar visual markers for events, candidates, and bookings."""
        # Clear existing tags
        self.calendar.calevent_remove("all")

        # Add Google Calendar events (blue)
        for ev in self._gcal_events:
            ev_date = ev["start"].date() if isinstance(ev["start"], datetime) else ev["start"]
            self.calendar.calevent_create(
                ev_date,
                ev["summary"],
                "gcal",
            )

        # Add candidate dates (yellow)
        for d in self._candidate_dates:
            self.calendar.calevent_create(d, "候補日", "candidate")

        # Add booked dates (green)
        for d in self._booked_dates:
            self.calendar.calevent_create(d, "予約済", "booked")

        self.calendar.tag_config("gcal", background=COLOR_GCAL_EVENT, foreground="white")
        self.calendar.tag_config("candidate", background=COLOR_CANDIDATE, foreground="black")
        self.calendar.tag_config("booked", background=COLOR_BOOKED, foreground="white")

    def _on_month_changed(self, _event=None):
        """Refresh events when the displayed month changes."""
        self._refresh_calendar_tags()

    def _on_date_click(self, _event=None):
        """Toggle a date as candidate when clicked on the calendar."""
        selected = self.calendar.selection_get()
        if not selected:
            return

        if isinstance(selected, datetime):
            selected = selected.date()

        # Don't allow selecting past dates
        if selected < date.today():
            return

        if selected in self._candidate_dates:
            self._candidate_dates.discard(selected)
        else:
            self._candidate_dates.add(selected)

        self._refresh_candidate_list()
        self._refresh_calendar_tags()

    def _on_restaurant_select(self, _event=None):
        """Handle restaurant selection change."""
        pass

    def _open_browser(self):
        """Open the restaurant browser dialog."""
        browser = RestaurantBrowserDialog(self.root, self.config)
        self.root.wait_window(browser.dialog)

        new_restaurants = browser.get_selected_restaurants()
        if new_restaurants:
            for r in new_restaurants:
                if not any(t.omakase_url == r.omakase_url for t in self.config.target_restaurants):
                    self.config.target_restaurants.append(r)
            self._load_restaurants()
            self._log(f"{len(new_restaurants)} 件のレストランを追加しました")

    def _remove_restaurant(self):
        """Remove selected restaurant(s) from the target list."""
        sel = self.restaurant_listbox.curselection()
        if not sel:
            return
        # Remove in reverse order to preserve indices
        for idx in reversed(sel):
            if idx < len(self.config.target_restaurants):
                removed = self.config.target_restaurants.pop(idx)
                self._log(f"「{removed.name}」を削除しました")
        self._load_restaurants()

    def _refresh_candidate_list(self):
        """Update the candidate dates listbox."""
        self.candidate_listbox.delete(0, tk.END)
        for d in sorted(self._candidate_dates):
            weekday = ["月", "火", "水", "木", "金", "土", "日"][d.weekday()]
            self.candidate_listbox.insert(
                tk.END,
                f"{d.strftime('%Y-%m-%d')} ({weekday})",
            )

    def _remove_candidate(self):
        """Remove selected candidate date."""
        sel = self.candidate_listbox.curselection()
        if not sel:
            return
        dates_sorted = sorted(self._candidate_dates)
        if sel[0] < len(dates_sorted):
            self._candidate_dates.discard(dates_sorted[sel[0]])
            self._refresh_candidate_list()
            self._refresh_calendar_tags()

    def _clear_candidates(self):
        """Clear all candidate dates."""
        self._candidate_dates.clear()
        self._refresh_candidate_list()
        self._refresh_calendar_tags()

    # ── Booking ───────────────────────────────────────────────

    def _start_booking(self):
        """Start the booking process in a background thread."""
        if self.continuous_var.get():
            # Continuous mode: monitor all restaurants
            if not self.config.target_restaurants:
                messagebox.showwarning("選択エラー", "レストランを追加してください")
                return
            targets = list(self.config.target_restaurants)
        else:
            # Single restaurant mode
            restaurant = self._get_selected_restaurant()
            if not restaurant:
                messagebox.showwarning("選択エラー", "レストランを選択してください")
                return
            targets = [restaurant]

        if not self._candidate_dates:
            messagebox.showwarning("候補日なし", "カレンダーから予約候補日を選択してください")
            return

        # Update candidate_dates for all targets
        date_strs = [d.strftime("%Y-%m-%d") for d in sorted(self._candidate_dates)]
        for t in targets:
            t.candidate_dates = list(date_strs)

        self.start_btn.configure(state=DISABLED)
        self.stop_btn.configure(state=NORMAL)
        self.progress.start(10)
        self._stop_event.clear()

        self._booking_thread = threading.Thread(
            target=self._booking_worker_multi,
            args=(targets,),
            daemon=True,
        )
        self._booking_thread.start()

    def _stop_booking(self):
        """Stop the booking process."""
        self._stop_event.set()
        self._update_status("停止中...")
        self._log("予約処理を停止中...")

    def _booking_worker_multi(self, targets: list[RestaurantTarget]):
        """Background worker that runs the booking loop for multiple restaurants."""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._booking_loop_multi(targets))
        except Exception as e:
            self._log(f"エラー: {e}")
            logger.exception("Booking worker error")
        finally:
            loop.close()
            self.root.after(0, self._booking_finished)

    async def _booking_loop_multi(self, targets: list[RestaurantTarget]):
        """Async booking loop that monitors multiple restaurants continuously."""
        self._update_status("ログイン中...")
        continuous = self.continuous_var.get()
        mode_label = "常時監視" if continuous else "通常"
        self._log(f"予約開始 ({mode_label}): {len(targets)} 件のレストラン")

        client = OmakaseClient(self.config)
        try:
            await client.start()
            self._log("ログイン成功")

            # Detect open times & scrape policies for all targets
            open_times: dict[str, str | None] = {}
            policies: dict[str, str] = {}

            for restaurant in targets:
                if self._stop_event.is_set():
                    break
                self._update_status(f"情報取得中: {restaurant.name}")
                try:
                    ot = await client.detect_reservation_open_time(restaurant)
                    open_times[restaurant.omakase_url] = ot
                    if ot:
                        self._log(f"  {restaurant.name}: 予約開始 {ot}")
                except Exception:
                    logger.exception("Failed to detect open time for %s", restaurant.name)

                try:
                    pol = await client.scrape_cancellation_policy(restaurant)
                    policies[restaurant.omakase_url] = pol
                except Exception:
                    logger.exception("Failed to scrape policy for %s", restaurant.name)

            attempt = 0
            while not self._stop_event.is_set():
                attempt += 1
                self._update_status(f"空き枠確認中... (サイクル {attempt})")
                self._log(f"--- サイクル {attempt} ---")

                booked_this_cycle = False

                for restaurant in targets:
                    if self._stop_event.is_set():
                        break

                    self._log(f"  [{restaurant.name}] 確認中...")

                    # Check availability
                    try:
                        slots = await client.check_availability(restaurant)
                    except Exception as e:
                        self._log(f"  [{restaurant.name}] エラー: {e}")
                        continue

                    if not slots:
                        self._log(f"  [{restaurant.name}] 空き枠なし")
                        continue

                    self._log(f"  [{restaurant.name}] {len(slots)} 件の空き枠")

                    # Try to match and book
                    for d in sorted(self._candidate_dates):
                        date_str = d.strftime("%Y-%m-%d")
                        for slot in slots:
                            slot_date = slot.get("date")
                            slot_time = slot.get("time")
                            if not slot_date or not slot_time:
                                continue
                            if slot_date != date_str:
                                continue
                            if slot_time not in restaurant.preferred_times:
                                continue

                            # Skip already booked
                            key = (restaurant.omakase_url, slot_date, slot_time)
                            if key in self._booked_keys:
                                continue

                            self._log(f"  [{restaurant.name}] マッチ! {date_str} {slot_time}")
                            self._update_status(f"予約確保中: {restaurant.name} {date_str} {slot_time}")

                            try:
                                reserved = await client.reserve_slot(
                                    restaurant, date_str, slot_time
                                )
                                if not reserved:
                                    self._log(f"  [{restaurant.name}] 予約確保失敗")
                                    continue

                                self._log(f"  [{restaurant.name}] 枠確保完了。承認待ち...")

                                cancellation_policy = policies.get(restaurant.omakase_url, "")
                                approval_result = await self._request_payment_approval(
                                    restaurant, date_str, slot_time, cancellation_policy
                                )

                                if approval_result == APPROVED:
                                    self._log("承認されました。決済を実行中...")
                                    self._update_status(f"決済中: {restaurant.name}")
                                    paid = await client.complete_payment()
                                    if paid:
                                        self._booked_keys.add(key)
                                        self._log(f"予約・決済完了! {restaurant.name} {date_str} {slot_time}")
                                        self._on_booking_success(restaurant, date_str, slot_time)
                                        booked_this_cycle = True
                                        if not continuous:
                                            return
                                    else:
                                        self._log(f"  [{restaurant.name}] 決済失敗")
                                elif approval_result == REJECTED:
                                    self._log(f"  [{restaurant.name}] 却下されました")
                                    self._booked_keys.add(key)  # Don't retry rejected
                                else:
                                    self._log(f"  [{restaurant.name}] 承認タイムアウト")

                            except Exception as e:
                                self._log(f"  [{restaurant.name}] エラー: {e}")

                # In non-continuous mode, stop after one successful booking
                if booked_this_cycle and not continuous:
                    break

                # Determine polling interval
                best_open_time = None
                for restaurant in targets:
                    ot = open_times.get(restaurant.omakase_url)
                    if ot:
                        best_open_time = ot
                        break
                interval = self._get_poll_interval(best_open_time)

                # In continuous mode, use cancellation check interval when no open time is near
                if continuous and interval == self.config.check_interval_seconds:
                    interval = min(interval, self.config.cancellation_check_interval_seconds)

                self._log(f"次の確認まで {interval}秒")

                for _ in range(int(interval / 0.1)):
                    if self._stop_event.is_set():
                        break
                    await asyncio.sleep(0.1)

            self._log("予約処理を停止しました")
            self._update_status("停止")

        except OmakaseBookingError as e:
            self._log(f"ログインエラー: {e}")
            self._update_status("ログインエラー")
        finally:
            await client.close()

    async def _request_payment_approval(
        self,
        restaurant: RestaurantTarget,
        date_str: str,
        time_str: str,
        cancellation_policy: str = "",
    ) -> str:
        """Request payment approval via Google Chat or GUI dialog.

        Returns: "approved", "rejected", or "pending" (timeout).
        """
        if self.config.gchat_webhook_url:
            # Send approval request to Google Chat and wait
            self._log("Google Chat に承認依頼を送信中...")
            self._update_status("承認待ち (Google Chat)")

            result = await request_approval(
                webhook_url=self.config.gchat_webhook_url,
                restaurant_name=restaurant.name,
                booking_date=date_str,
                booking_time=time_str,
                party_size=restaurant.party_size,
                fee_per_person=self.config.approval_fee_per_person,
                callback_url=self.config.gchat_callback_url or None,
                timeout_seconds=self.config.approval_timeout_seconds,
                cancellation_policy=cancellation_policy,
            )

            if result == PENDING:
                # Timeout - fall back to GUI dialog
                self._log("Google Chat からの応答がありません。アプリで確認します。")
                return await self._gui_approval_dialog(restaurant, date_str, time_str, cancellation_policy)

            return result
        else:
            # No Google Chat configured - use GUI dialog
            return await self._gui_approval_dialog(restaurant, date_str, time_str, cancellation_policy)

    async def _gui_approval_dialog(
        self,
        restaurant: RestaurantTarget,
        date_str: str,
        time_str: str,
        cancellation_policy: str = "",
    ) -> str:
        """Show a GUI confirmation dialog for payment approval."""
        total_fee = self.config.approval_fee_per_person * restaurant.party_size
        future = asyncio.get_event_loop().create_future()

        msg = (
            f"以下の予約の決済を実行しますか？\n\n"
            f"レストラン: {restaurant.name}\n"
            f"日時: {date_str} {time_str}\n"
            f"人数: {restaurant.party_size}名\n"
            f"手数料: ¥{self.config.approval_fee_per_person:,} x {restaurant.party_size}名"
            f" = ¥{total_fee:,}\n"
        )
        if cancellation_policy:
            # Truncate for dialog readability
            policy_display = cancellation_policy[:200] + "..." if len(cancellation_policy) > 200 else cancellation_policy
            msg += f"\n【キャンセルポリシー】\n{policy_display}\n"

        def _show_dialog():
            result = messagebox.askyesno("決済承認", msg)
            self.root.after(0, lambda: future.get_loop().call_soon_threadsafe(
                future.set_result, APPROVED if result else REJECTED
            ))

        self.root.after(0, _show_dialog)
        return await future

    def _get_poll_interval(self, open_time_str: str | None) -> float:
        """Calculate polling interval based on proximity to open time."""
        if not open_time_str:
            return self.config.check_interval_seconds

        now = datetime.now()
        window = timedelta(minutes=self.config.fast_poll_window_minutes)

        try:
            if "T" in open_time_str:
                open_dt = datetime.strptime(open_time_str, "%Y-%m-%dT%H:%M")
            else:
                hour, minute = map(int, open_time_str.split(":"))
                open_dt = now.replace(hour=hour, minute=minute, second=0, microsecond=0)

            if abs((now - open_dt).total_seconds()) < window.total_seconds():
                return self.config.fast_poll_interval_seconds
        except ValueError:
            pass

        return self.config.check_interval_seconds

    def _on_booking_success(self, restaurant: RestaurantTarget, date_str: str, time_str: str):
        """Handle a successful booking - add to calendar."""
        booked_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        self._booked_dates.add(booked_date)
        self._candidate_dates.discard(booked_date)

        # Create Google Calendar event
        try:
            event_id = create_booking_event(
                self.config,
                restaurant.name,
                date_str,
                time_str,
                restaurant.party_size,
            )
            if event_id:
                self._log(f"カレンダーに予定を追加しました (ID: {event_id})")
            else:
                self._log("カレンダーへの追加に失敗しました")
        except Exception as e:
            self._log(f"カレンダー追加エラー: {e}")

        # Refresh UI on main thread
        self.root.after(0, self._refresh_candidate_list)
        self.root.after(0, self._refresh_calendar_tags)
        self.root.after(0, self._sync_calendar)

        self.root.after(0, lambda: messagebox.showinfo(
            "予約完了",
            f"{restaurant.name}\n{date_str} {time_str}\n{restaurant.party_size}名\n\nカレンダーに登録しました",
        ))

    def _booking_finished(self):
        """Called on main thread when booking worker finishes."""
        self.start_btn.configure(state=NORMAL)
        self.stop_btn.configure(state=DISABLED)
        self.progress.stop()
        if self.status_var.get() not in ("停止", "ログインエラー"):
            self._update_status("完了")

    # ── Helpers ────────────────────────────────────────────────

    def _update_status(self, text: str):
        """Update the status label (thread-safe)."""
        self.root.after(0, lambda: self.status_var.set(text))

    def _log(self, message: str):
        """Append a message to the log panel (thread-safe)."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        line = f"[{timestamp}] {message}\n"

        def _append():
            self.log_text.configure(state=tk.NORMAL)
            self.log_text.insert(tk.END, line)
            self.log_text.see(tk.END)
            self.log_text.configure(state=tk.DISABLED)

        self.root.after(0, _append)

    def _on_close(self):
        """Handle window close."""
        if self._booking_thread and self._booking_thread.is_alive():
            if not messagebox.askyesno(
                "確認",
                "予約処理が実行中です。終了しますか？",
            ):
                return
            self._stop_event.set()

        self.root.destroy()

    def run(self):
        """Start the application."""
        self.root.mainloop()
