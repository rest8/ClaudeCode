"""ポーリング本体: 監視対象店舗を1回だけ取得し、配信先ごとに通知。"""
from __future__ import annotations

import logging
import threading

from .config import AppConfig
from .notifier import Notifier
from .restaurants import RestaurantDirectory
from .scraper import OmakaseScraper, filter_slots
from .state import StateStore
from .subscribers import SubscriberStore

LOGGER = logging.getLogger(__name__)


class App:
    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._scraper = OmakaseScraper(user_agent=config.user_agent, cookies=config.cookies)
        self._notifier = Notifier(config.notifications)
        self._state = StateStore(config.state_file)
        self._restaurants = RestaurantDirectory(config.restaurants_file)
        self._subscribers = SubscriberStore(config.subscribers_file)
        self._stop_event = threading.Event()
        self._wake_event = threading.Event()

    def stop(self) -> None:
        LOGGER.info("停止要求を受信")
        self._stop_event.set()
        self._wake_event.set()

    def trigger_check_now(self) -> None:
        LOGGER.info("即時チェックを要求")
        self._wake_event.set()

    def run(self) -> None:
        LOGGER.info(
            "監視開始: 配信先=%d / 対象店舗=%d / 間隔=%d秒",
            len(self._subscribers.all()),
            len(self._subscribers.watched_restaurant_ids()),
            self._config.poll_interval_seconds,
        )
        while not self._stop_event.is_set():
            self.check_all()
            self._wake_event.wait(timeout=self._config.poll_interval_seconds)
            self._wake_event.clear()
        LOGGER.info("監視終了")

    def check_all(self) -> None:
        watched = self._subscribers.watched_restaurant_ids()
        if not watched:
            LOGGER.debug("監視対象なし")
            return
        for rid in watched:
            self._check_restaurant(rid)

    def _check_restaurant(self, restaurant_id: str) -> None:
        info = self._restaurants.get(restaurant_id)
        if info is None:
            LOGGER.warning(
                "店舗情報未登録: %s (`discover` を実行してください)", restaurant_id
            )
            return
        try:
            slots = self._scraper.fetch_url(info.url)
        except Exception as e:  # noqa: BLE001
            LOGGER.exception("取得エラー: %s (%s)", info.name, e)
            return

        for sub in self._subscribers.subscribers_for_restaurant(restaurant_id):
            subscription = sub.find_subscription(restaurant_id)
            if subscription is None:
                continue
            filtered = filter_slots(
                slots,
                dates=subscription.dates,
                times=subscription.times,
                party_size=subscription.party_size,
            )
            current_keys = {s.key() for s in filtered}
            previous_keys = self._state.previous(sub.id, restaurant_id)
            new_keys = current_keys - previous_keys

            if new_keys:
                new_slots = [s for s in filtered if s.key() in new_keys]
                LOGGER.info(
                    "空席検知: %s -> %s (%d件)",
                    sub.id,
                    info.name,
                    len(new_slots),
                )
                self._notifier.notify(sub, info.name, info.url, new_slots)

            self._state.update(sub.id, restaurant_id, current_keys)
