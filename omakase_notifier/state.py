"""空席状態の永続化。前回検知した空席との差分で「新規に空いた」枠を判定する。"""
from __future__ import annotations

import json
from pathlib import Path


class StateStore:
    def __init__(self, path: str) -> None:
        self._path = Path(path)
        self._data: dict[str, list[str]] = {}
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

    def previous_slots(self, target_name: str) -> set[str]:
        return set(self._data.get(target_name, []))

    def update(self, target_name: str, slots: set[str]) -> None:
        self._data[target_name] = sorted(slots)
        self.save()
