"""配信先（メール/LINE 宛先）と購読店舗の管理。

`subscribers.yaml` の例:

```yaml
subscribers:
  - id: alice
    label: "Alice"
    channel: email           # email | line | webhook
    destination: "alice@example.com"
    subscriptions:
      - restaurant_id: abc123
        dates: ["2026-05-15"]
        times: []
        party_size: 2
```
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

import yaml

LOGGER = logging.getLogger(__name__)
VALID_CHANNELS = ("email", "line", "webhook")
ID_RE = re.compile(r"^[a-zA-Z0-9_-]+$")


@dataclass
class Subscription:
    restaurant_id: str
    dates: list[str] = field(default_factory=list)
    times: list[str] = field(default_factory=list)
    party_size: int | None = None

    def to_dict(self) -> dict:
        d: dict = {"restaurant_id": self.restaurant_id}
        if self.dates:
            d["dates"] = list(self.dates)
        if self.times:
            d["times"] = list(self.times)
        if self.party_size is not None:
            d["party_size"] = self.party_size
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Subscription":
        return cls(
            restaurant_id=d["restaurant_id"],
            dates=list(d.get("dates") or []),
            times=list(d.get("times") or []),
            party_size=d.get("party_size"),
        )


@dataclass
class Subscriber:
    id: str
    channel: str
    destination: str
    label: str = ""
    subscriptions: list[Subscription] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "label": self.label,
            "channel": self.channel,
            "destination": self.destination,
            "subscriptions": [s.to_dict() for s in self.subscriptions],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Subscriber":
        return cls(
            id=d["id"],
            channel=d["channel"],
            destination=d["destination"],
            label=d.get("label", ""),
            subscriptions=[Subscription.from_dict(s) for s in d.get("subscriptions", [])],
        )

    def find_subscription(self, restaurant_id: str) -> Subscription | None:
        for s in self.subscriptions:
            if s.restaurant_id == restaurant_id:
                return s
        return None


class SubscriberStore:
    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._subscribers: dict[str, Subscriber] = {}
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            raw = yaml.safe_load(self._path.read_text(encoding="utf-8")) or {}
        except (yaml.YAMLError, OSError) as e:
            LOGGER.warning("subscribers の読み込み失敗: %s", e)
            return
        for s in raw.get("subscribers") or []:
            try:
                sub = Subscriber.from_dict(s)
            except KeyError as e:
                LOGGER.warning("subscriber 不正レコード: %s", e)
                continue
            if sub.channel not in VALID_CHANNELS:
                LOGGER.warning("未対応チャネル: %s", sub.channel)
                continue
            self._subscribers[sub.id] = sub

    def save(self) -> None:
        payload = {"subscribers": [s.to_dict() for s in self.all()]}
        self._path.write_text(
            yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )

    def all(self) -> list[Subscriber]:
        return sorted(self._subscribers.values(), key=lambda s: s.id)

    def get(self, sid: str) -> Subscriber | None:
        return self._subscribers.get(sid)

    def add(self, subscriber: Subscriber) -> None:
        if not ID_RE.match(subscriber.id):
            raise ValueError("id は英数字/_/- のみ使用できます")
        if subscriber.channel not in VALID_CHANNELS:
            raise ValueError(f"channel は {VALID_CHANNELS} のいずれか")
        if not subscriber.destination:
            raise ValueError("destination は必須です")
        if subscriber.id in self._subscribers:
            raise ValueError(f"id 重複: {subscriber.id}")
        self._subscribers[subscriber.id] = subscriber
        self.save()

    def remove(self, sid: str) -> bool:
        if sid in self._subscribers:
            del self._subscribers[sid]
            self.save()
            return True
        return False

    def subscribe(
        self,
        subscriber_id: str,
        restaurant_id: str,
        dates: list[str] | None = None,
        times: list[str] | None = None,
        party_size: int | None = None,
    ) -> Subscription:
        sub = self._require(subscriber_id)
        existing = sub.find_subscription(restaurant_id)
        if existing is not None:
            existing.dates = list(dates or [])
            existing.times = list(times or [])
            existing.party_size = party_size
            self.save()
            return existing
        new_sub = Subscription(
            restaurant_id=restaurant_id,
            dates=list(dates or []),
            times=list(times or []),
            party_size=party_size,
        )
        sub.subscriptions.append(new_sub)
        self.save()
        return new_sub

    def unsubscribe(self, subscriber_id: str, restaurant_id: str) -> bool:
        sub = self._require(subscriber_id)
        before = len(sub.subscriptions)
        sub.subscriptions = [s for s in sub.subscriptions if s.restaurant_id != restaurant_id]
        if len(sub.subscriptions) != before:
            self.save()
            return True
        return False

    def watched_restaurant_ids(self) -> set[str]:
        out: set[str] = set()
        for s in self._subscribers.values():
            for sub in s.subscriptions:
                out.add(sub.restaurant_id)
        return out

    def subscribers_for_restaurant(self, restaurant_id: str) -> list[Subscriber]:
        return [s for s in self._subscribers.values() if s.find_subscription(restaurant_id)]

    def _require(self, sid: str) -> Subscriber:
        sub = self._subscribers.get(sid)
        if sub is None:
            raise KeyError(f"subscriber が見つかりません: {sid}")
        return sub
