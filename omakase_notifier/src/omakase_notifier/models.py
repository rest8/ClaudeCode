from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    email: Mapped[Optional[str]] = mapped_column(String(256), default=None)
    line_user_id: Mapped[Optional[str]] = mapped_column(String(64), default=None)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    subscriptions: Mapped[list["Subscription"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class Restaurant(Base):
    __tablename__ = "restaurants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    omakase_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(256))
    url: Mapped[str] = mapped_column(String(512))
    area: Mapped[Optional[str]] = mapped_column(String(128), default=None)
    genre: Mapped[Optional[str]] = mapped_column(String(128), default=None)
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    subscriptions: Mapped[list["Subscription"]] = relationship(
        back_populates="restaurant", cascade="all, delete-orphan"
    )


class Subscription(Base):
    __tablename__ = "subscriptions"
    __table_args__ = (UniqueConstraint("user_id", "restaurant_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    restaurant_id: Mapped[int] = mapped_column(
        ForeignKey("restaurants.id", ondelete="CASCADE")
    )
    notify_email: Mapped[bool] = mapped_column(Boolean, default=True)
    notify_line: Mapped[bool] = mapped_column(Boolean, default=False)
    party_size_min: Mapped[int] = mapped_column(Integer, default=1)
    party_size_max: Mapped[int] = mapped_column(Integer, default=8)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    user: Mapped[User] = relationship(back_populates="subscriptions")
    restaurant: Mapped[Restaurant] = relationship(back_populates="subscriptions")


class AvailabilitySnapshot(Base):
    """Latest known availability slot for a restaurant. Used to detect
    transitions from "no seats" -> "open" so a notification fires only
    on the moment of opening, not on every poll while seats remain open.
    """

    __tablename__ = "availability_snapshots"
    __table_args__ = (
        UniqueConstraint("restaurant_id", "slot_datetime", "party_size"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(
        ForeignKey("restaurants.id", ondelete="CASCADE"), index=True
    )
    slot_datetime: Mapped[datetime] = mapped_column(DateTime)
    party_size: Mapped[int] = mapped_column(Integer)
    available: Mapped[bool] = mapped_column(Boolean, default=False)
    price_jpy: Mapped[Optional[int]] = mapped_column(Integer, default=None)
    cancellation_policy: Mapped[Optional[str]] = mapped_column(Text, default=None)
    last_checked_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class NotificationLog(Base):
    __tablename__ = "notification_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    restaurant_id: Mapped[int] = mapped_column(
        ForeignKey("restaurants.id", ondelete="CASCADE")
    )
    channel: Mapped[str] = mapped_column(String(16))  # "email" or "line"
    slot_datetime: Mapped[datetime] = mapped_column(DateTime)
    party_size: Mapped[int] = mapped_column(Integer)
    sent_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    success: Mapped[bool] = mapped_column(Boolean, default=True)
    error: Mapped[Optional[str]] = mapped_column(Text, default=None)


@dataclass
class AvailabilitySlot:
    """In-memory representation of a single open slot returned by the crawler."""

    slot_datetime: datetime
    party_size: int
    price_jpy: Optional[int] = None
    cancellation_policy: Optional[str] = None
