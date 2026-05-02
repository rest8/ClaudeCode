"""(配信先 × 店舗) 単位で通知済み枠を保存する。"""
from __future__ import annotations

import json
from pathlib import Path


class StateStore:
    def __init__(self, path: str) -> None:
        self._path = Path(path)
        # data[subscriber_id][restaurant_id] = sorted list of slot keys
        self._data: dict[str, dict[str, list[str]]] = {}
        self._load()

    def _load(self) -> None:
        if self._path.exists():
            try:
                self._data = json.loads(self._path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                self._data = {}

    def save(self) -> None:
        self._path.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def previous(self, subscriber_id: str, restaurant_id: str) -> set[str]:
        return set(self._data.get(subscriber_id, {}).get(restaurant_id, []))

    def update(self, subscriber_id: str, restaurant_id: str, slot_keys: set[str]) -> None:
        self._data.setdefault(subscriber_id, {})[restaurant_id] = sorted(slot_keys)
        self.save()

    def forget_subscriber(self, subscriber_id: str) -> None:
        self._data.pop(subscriber_id, None)
        self.save()
