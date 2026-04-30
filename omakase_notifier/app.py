"""アプリケーション本体: ポーリングループと通知ディスパッチ。"""
from __future__ import annotations

import logging
import threading
import time

from .config import AppConfig
from .notifier import Notifier
from .scraper import OmakaseScraper
from .state import StateStore

LOGGER = logging.getLogger(__name__)


class App:
    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._scraper = OmakaseScraper(config)
        self._notifier = Notifier(config.notifications)
        self._state = StateStore(config.state_file)
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
            "監視開始: %d店舗 / 間隔=%d秒",
            len(self._config.targets),
            self._config.poll_interval_seconds,
        )
        while not self._stop_event.is_set():
            self._check_all()
            self._wake_event.wait(timeout=self._config.poll_interval_seconds)
            self._wake_event.clear()
        LOGGER.info("監視終了")

    def _check_all(self) -> None:
        for target in self._config.targets:
            try:
                slots = self._scraper.fetch(target)
            except Exception as e:  # noqa: BLE001
                LOGGER.exception("取得エラー: %s (%s)", target.name, e)
                continue

            current_keys = {s.key() for s in slots}
            previous_keys = self._state.previous_slots(target.name)
            new_keys = current_keys - previous_keys

            if new_keys:
                new_slots = [s for s in slots if s.key() in new_keys]
                LOGGER.info("空席検知: %s -> %d件 新規", target.name, len(new_slots))
                self._notifier.notify(target.name, new_slots)
            else:
                LOGGER.debug("空席変化なし: %s (%d件)", target.name, len(current_keys))

            self._state.update(target.name, current_keys)
