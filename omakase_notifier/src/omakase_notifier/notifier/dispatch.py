from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from ..config import Config
from ..models import (
    AvailabilitySlot,
    NotificationLog,
    Restaurant,
    Subscription,
    User,
)
from .email import EmailNotifier
from .line import LineNotifier

log = logging.getLogger(__name__)


class NotificationDispatcher:
    def __init__(self, config: Config):
        self.email = EmailNotifier(config.email)
        self.line = LineNotifier(config.line)

    def notify_open_slots(
        self,
        session: Session,
        restaurant: Restaurant,
        new_slots: list[AvailabilitySlot],
    ) -> None:
        if not new_slots:
            return
        subs = (
            session.query(Subscription)
            .filter(Subscription.restaurant_id == restaurant.id)
            .all()
        )
        for sub in subs:
            user = session.get(User, sub.user_id)
            if not user or not user.enabled:
                continue
            relevant = [
                s
                for s in new_slots
                if sub.party_size_min <= s.party_size <= sub.party_size_max
            ]
            if not relevant:
                continue
            subject, body = _format_message(restaurant, relevant)
            if sub.notify_email and user.email:
                self._safe_send(
                    session,
                    user_id=user.id,
                    restaurant_id=restaurant.id,
                    channel="email",
                    slots=relevant,
                    send=lambda: self.email.send(user.email, subject, body),
                )
            if sub.notify_line and user.line_user_id:
                self._safe_send(
                    session,
                    user_id=user.id,
                    restaurant_id=restaurant.id,
                    channel="line",
                    slots=relevant,
                    send=lambda: self.line.send(
                        user.line_user_id, f"{subject}\n\n{body}"
                    ),
                )

    def _safe_send(
        self,
        session: Session,
        *,
        user_id: int,
        restaurant_id: int,
        channel: str,
        slots: list[AvailabilitySlot],
        send,
    ) -> None:
        error: Optional[str] = None
        try:
            send()
            success = True
        except Exception as exc:  # noqa: BLE001
            success = False
            error = str(exc)
            log.exception("Notification (%s) failed", channel)
        for s in slots:
            session.add(
                NotificationLog(
                    user_id=user_id,
                    restaurant_id=restaurant_id,
                    channel=channel,
                    slot_datetime=s.slot_datetime,
                    party_size=s.party_size,
                    sent_at=datetime.utcnow(),
                    success=success,
                    error=error,
                )
            )


def _format_message(
    restaurant: Restaurant, slots: list[AvailabilitySlot]
) -> tuple[str, str]:
    subject = f"【空席通知】{restaurant.name}"
    lines = [f"{restaurant.name} に空席が出ました。", "", f"店舗ページ: {restaurant.url}", ""]
    for s in slots:
        lines.append(f"・日時: {s.slot_datetime.strftime('%Y-%m-%d %H:%M')}")
        lines.append(f"  人数: {s.party_size} 名")
        if s.price_jpy is not None:
            lines.append(f"  料金: {s.price_jpy:,} 円")
        if s.cancellation_policy:
            lines.append(f"  キャンセル規定: {s.cancellation_policy}")
        lines.append("")
    return subject, "\n".join(lines)
