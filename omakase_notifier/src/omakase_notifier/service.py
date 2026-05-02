"""Core service: schedules list refresh and availability polling, and
fires notifications on transitions from "no seats" to "available".

The service is designed to be embedded in a single Python process. The
admin UI imports `Service` and calls its methods to inspect/control state.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime
from typing import Callable, Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select

from .config import Config
from .crawler import OmakaseCrawler, RestaurantInfo
from .db import session_scope
from .models import (
    AvailabilitySnapshot,
    Restaurant,
    Subscription,
)
from .notifier import NotificationDispatcher

log = logging.getLogger(__name__)

LogCallback = Callable[[str], None]


class Service:
    def __init__(self, config: Config, on_log: Optional[LogCallback] = None):
        self.config = config
        self.on_log = on_log or (lambda _msg: None)
        self.crawler = OmakaseCrawler(
            headless=config.app.headless,
            user_agent=config.app.user_agent,
        )
        self.dispatcher = NotificationDispatcher(config)
        self.scheduler = BackgroundScheduler(timezone="Asia/Tokyo")
        self._poll_job_id = "availability_poll"
        self._list_job_id = "restaurant_list_refresh"
        self._lock = threading.Lock()

    # -------- Lifecycle --------
    def start(self) -> None:
        if self.scheduler.running:
            return
        self.scheduler.start()
        self._reschedule_poll(self.config.app.poll_interval_seconds)
        self._reschedule_list(self.config.app.list_refresh_time)
        self._log("Service started.")

    def stop(self) -> None:
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)
        self._log("Service stopped.")

    @property
    def running(self) -> bool:
        return self.scheduler.running

    # -------- Scheduling --------
    def set_poll_interval(self, seconds: float) -> None:
        if seconds < 0.1:
            raise ValueError("poll interval must be >= 0.1s")
        self.config.app.poll_interval_seconds = seconds
        self._reschedule_poll(seconds)
        self._log(f"Poll interval set to {seconds:g}s.")

    def _reschedule_poll(self, seconds: float) -> None:
        if not self.scheduler.running:
            return
        self.scheduler.add_job(
            self._run_availability_poll,
            trigger=IntervalTrigger(seconds=seconds),
            id=self._poll_job_id,
            replace_existing=True,
            coalesce=True,
            max_instances=1,
            next_run_time=datetime.now(),
        )

    def _reschedule_list(self, hhmm: str) -> None:
        if not self.scheduler.running:
            return
        h, m = (int(x) for x in hhmm.split(":"))
        self.scheduler.add_job(
            self.refresh_restaurant_list,
            trigger=CronTrigger(hour=h, minute=m),
            id=self._list_job_id,
            replace_existing=True,
        )

    # -------- Jobs --------
    def refresh_restaurant_list(self) -> int:
        """Re-fetch the master list of restaurants and upsert into DB.
        Returns the number of restaurants seen."""
        with self._lock:
            self._log("Refreshing restaurant list...")
            try:
                items = self.crawler.fetch_restaurant_list()
            except Exception as exc:  # noqa: BLE001
                self._log(f"Restaurant list fetch failed: {exc}")
                return 0
            with session_scope() as session:
                for info in items:
                    self._upsert_restaurant(session, info)
            self._log(f"Restaurant list refreshed: {len(items)} entries.")
            return len(items)

    def _upsert_restaurant(self, session, info: RestaurantInfo) -> Restaurant:
        existing = (
            session.execute(
                select(Restaurant).where(Restaurant.omakase_id == info.omakase_id)
            )
            .scalars()
            .first()
        )
        if existing:
            existing.name = info.name
            existing.url = info.url
            existing.area = info.area or existing.area
            existing.genre = info.genre or existing.genre
            return existing
        r = Restaurant(
            omakase_id=info.omakase_id,
            name=info.name,
            url=info.url,
            area=info.area,
            genre=info.genre,
        )
        session.add(r)
        session.flush()
        return r

    def _run_availability_poll(self) -> None:
        if not self._lock.acquire(blocking=False):
            return  # previous run still in progress; skip
        try:
            self._poll_all()
        finally:
            self._lock.release()

    def _poll_all(self) -> None:
        with session_scope() as session:
            subs = session.query(Subscription).all()
            restaurant_ids = sorted({s.restaurant_id for s in subs})
            restaurants = (
                session.query(Restaurant)
                .filter(Restaurant.id.in_(restaurant_ids))
                .all()
                if restaurant_ids
                else []
            )
        for r in restaurants:
            self._poll_one(r.id)

    def _poll_one(self, restaurant_id: int) -> None:
        with session_scope() as session:
            r = session.get(Restaurant, restaurant_id)
            if not r:
                return
            try:
                slots = self.crawler.check_availability(r.url)
            except Exception as exc:  # noqa: BLE001
                log.warning("Poll failed for %s: %s", r.name, exc)
                return

            new_open: list = []
            seen_keys = set()
            for s in slots:
                key = (r.id, s.slot_datetime, s.party_size)
                seen_keys.add(key)
                snap = (
                    session.query(AvailabilitySnapshot)
                    .filter_by(
                        restaurant_id=r.id,
                        slot_datetime=s.slot_datetime,
                        party_size=s.party_size,
                    )
                    .first()
                )
                was_available = bool(snap and snap.available)
                if snap is None:
                    snap = AvailabilitySnapshot(
                        restaurant_id=r.id,
                        slot_datetime=s.slot_datetime,
                        party_size=s.party_size,
                        available=True,
                        price_jpy=s.price_jpy,
                        cancellation_policy=s.cancellation_policy,
                    )
                    session.add(snap)
                else:
                    snap.available = True
                    snap.price_jpy = s.price_jpy
                    snap.cancellation_policy = s.cancellation_policy
                if not was_available:
                    new_open.append(s)

            # Mark previously-known slots as unavailable if they didn't appear.
            for snap in (
                session.query(AvailabilitySnapshot)
                .filter(AvailabilitySnapshot.restaurant_id == r.id)
                .all()
            ):
                if (r.id, snap.slot_datetime, snap.party_size) not in seen_keys:
                    snap.available = False

            if new_open:
                self._log(
                    f"[{r.name}] {len(new_open)} new open slot(s); notifying."
                )
                self.dispatcher.notify_open_slots(session, r, new_open)

    # -------- Logging hook --------
    def _log(self, msg: str) -> None:
        log.info(msg)
        try:
            self.on_log(msg)
        except Exception:  # noqa: BLE001
            pass
