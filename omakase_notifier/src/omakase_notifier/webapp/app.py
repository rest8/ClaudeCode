from __future__ import annotations

import calendar as _cal
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from starlette.requests import Request

from ..config import Config, default_config_path
from ..db import session_scope
from ..models import (
    AvailabilitySnapshot,
    NotificationLog,
    Restaurant,
    Subscription,
    User,
)
from ..service import Service

WEBAPP_DIR = Path(__file__).resolve().parent
TEMPLATES = Jinja2Templates(directory=str(WEBAPP_DIR / "templates"))


class UserIn(BaseModel):
    name: str
    email: Optional[str] = None
    line_user_id: Optional[str] = None
    enabled: bool = True


class UserPatch(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    line_user_id: Optional[str] = None
    enabled: Optional[bool] = None


class SubscriptionIn(BaseModel):
    restaurant_id: int
    notify_email: bool = True
    notify_line: bool = False
    party_size_min: int = 1
    party_size_max: int = 8


class SettingsIn(BaseModel):
    poll_interval_seconds: Optional[float] = Field(None, ge=0.1)
    list_refresh_time: Optional[str] = None
    smtp_host: Optional[str] = None
    smtp_port: Optional[int] = None
    smtp_user: Optional[str] = None
    smtp_password: Optional[str] = None
    smtp_from: Optional[str] = None
    smtp_use_starttls: Optional[bool] = None
    line_token: Optional[str] = None


def create_app(service: Service) -> FastAPI:
    app = FastAPI(title="Omakase Notifier")

    app.mount(
        "/static",
        StaticFiles(directory=str(WEBAPP_DIR / "static")),
        name="static",
    )

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request):
        return TEMPLATES.TemplateResponse("index.html", {"request": request})

    # ---------- service status / control ----------
    @app.get("/api/status")
    def status():
        return {
            "running": service.running,
            "poll_interval_seconds": service.config.app.poll_interval_seconds,
            "list_refresh_time": service.config.app.list_refresh_time,
        }

    @app.post("/api/control/start")
    def control_start():
        service.start()
        return {"ok": True, "running": service.running}

    @app.post("/api/control/stop")
    def control_stop():
        service.stop()
        return {"ok": True, "running": service.running}

    @app.post("/api/control/poll-now")
    def control_poll_now():
        service.run_poll_now()
        return {"ok": True}

    # ---------- restaurants ----------
    @app.get("/api/restaurants")
    def list_restaurants(q: Optional[str] = None):
        with session_scope() as session:
            stmt = select(Restaurant).order_by(Restaurant.name)
            if q:
                stmt = stmt.where(Restaurant.name.ilike(f"%{q}%"))
            restaurants = list(session.execute(stmt).scalars())
            sub_counts = dict(
                session.execute(
                    select(
                        Subscription.restaurant_id,
                        func.count(Subscription.id),
                    ).group_by(Subscription.restaurant_id)
                ).all()
            )
            available_ids = {
                row[0]
                for row in session.execute(
                    select(AvailabilitySnapshot.restaurant_id)
                    .where(AvailabilitySnapshot.available == True)  # noqa: E712
                    .distinct()
                ).all()
            }
            return [
                {
                    "id": r.id,
                    "omakase_id": r.omakase_id,
                    "name": r.name,
                    "area": r.area,
                    "genre": r.genre,
                    "url": r.url,
                    "subscribers": sub_counts.get(r.id, 0),
                    "has_open_slots": r.id in available_ids,
                }
                for r in restaurants
            ]

    @app.post("/api/restaurants/refresh")
    def refresh_restaurants():
        n = service.refresh_restaurant_list()
        return {"ok": True, "count": n}

    # ---------- users ----------
    @app.get("/api/users")
    def list_users():
        with session_scope() as session:
            users = list(
                session.execute(select(User).order_by(User.id)).scalars()
            )
            sub_counts = dict(
                session.execute(
                    select(
                        Subscription.user_id, func.count(Subscription.id)
                    ).group_by(Subscription.user_id)
                ).all()
            )
            return [
                {
                    "id": u.id,
                    "name": u.name,
                    "email": u.email,
                    "line_user_id": u.line_user_id,
                    "enabled": u.enabled,
                    "subscriptions": sub_counts.get(u.id, 0),
                }
                for u in users
            ]

    @app.post("/api/users")
    def create_user(payload: UserIn):
        with session_scope() as session:
            u = User(
                name=payload.name,
                email=payload.email,
                line_user_id=payload.line_user_id,
                enabled=payload.enabled,
            )
            session.add(u)
            session.flush()
            return {"id": u.id}

    @app.get("/api/users/{user_id}")
    def get_user(user_id: int):
        with session_scope() as session:
            u = session.get(User, user_id)
            if not u:
                raise HTTPException(404, "user not found")
            subs = (
                session.execute(
                    select(Subscription, Restaurant)
                    .join(Restaurant, Restaurant.id == Subscription.restaurant_id)
                    .where(Subscription.user_id == user_id)
                ).all()
            )
            return {
                "id": u.id,
                "name": u.name,
                "email": u.email,
                "line_user_id": u.line_user_id,
                "enabled": u.enabled,
                "subscriptions": [
                    {
                        "id": s.id,
                        "restaurant_id": r.id,
                        "restaurant_name": r.name,
                        "notify_email": s.notify_email,
                        "notify_line": s.notify_line,
                        "party_size_min": s.party_size_min,
                        "party_size_max": s.party_size_max,
                    }
                    for s, r in subs
                ],
            }

    @app.put("/api/users/{user_id}")
    def update_user(user_id: int, patch: UserPatch):
        with session_scope() as session:
            u = session.get(User, user_id)
            if not u:
                raise HTTPException(404, "user not found")
            data = patch.model_dump(exclude_none=True)
            for k, v in data.items():
                setattr(u, k, v)
            return {"ok": True}

    @app.delete("/api/users/{user_id}")
    def delete_user(user_id: int):
        with session_scope() as session:
            u = session.get(User, user_id)
            if not u:
                raise HTTPException(404, "user not found")
            session.delete(u)
            return {"ok": True}

    # ---------- subscriptions ----------
    @app.post("/api/users/{user_id}/subscriptions")
    def add_subscription(user_id: int, payload: SubscriptionIn):
        with session_scope() as session:
            if not session.get(User, user_id):
                raise HTTPException(404, "user not found")
            if not session.get(Restaurant, payload.restaurant_id):
                raise HTTPException(404, "restaurant not found")
            existing = (
                session.execute(
                    select(Subscription).where(
                        Subscription.user_id == user_id,
                        Subscription.restaurant_id == payload.restaurant_id,
                    )
                )
                .scalars()
                .first()
            )
            if existing:
                existing.notify_email = payload.notify_email
                existing.notify_line = payload.notify_line
                existing.party_size_min = payload.party_size_min
                existing.party_size_max = payload.party_size_max
                return {"id": existing.id, "updated": True}
            sub = Subscription(
                user_id=user_id,
                restaurant_id=payload.restaurant_id,
                notify_email=payload.notify_email,
                notify_line=payload.notify_line,
                party_size_min=payload.party_size_min,
                party_size_max=payload.party_size_max,
            )
            session.add(sub)
            session.flush()
            return {"id": sub.id, "created": True}

    @app.delete("/api/subscriptions/{subscription_id}")
    def delete_subscription(subscription_id: int):
        with session_scope() as session:
            s = session.get(Subscription, subscription_id)
            if not s:
                raise HTTPException(404, "subscription not found")
            session.delete(s)
            return {"ok": True}

    # ---------- calendar ----------
    @app.get("/api/calendar/{year}/{month}")
    def calendar_month(year: int, month: int):
        if not (1 <= month <= 12):
            raise HTTPException(400, "invalid month")
        first = date(year, month, 1)
        days_in_month = _cal.monthrange(year, month)[1]
        last = date(year, month, days_in_month)
        with session_scope() as session:
            rows = session.execute(
                select(AvailabilitySnapshot, Restaurant)
                .join(
                    Restaurant,
                    Restaurant.id == AvailabilitySnapshot.restaurant_id,
                )
                .join(
                    Subscription,
                    Subscription.restaurant_id == AvailabilitySnapshot.restaurant_id,
                )
                .where(AvailabilitySnapshot.available == True)  # noqa: E712
                .where(AvailabilitySnapshot.slot_datetime >= datetime(first.year, first.month, first.day))
                .where(AvailabilitySnapshot.slot_datetime < datetime(last.year, last.month, last.day, 23, 59, 59))
                .distinct()
            ).all()
        # bucket by date string
        buckets: dict[str, set[int]] = {}
        for snap, _r in rows:
            key = snap.slot_datetime.strftime("%Y-%m-%d")
            buckets.setdefault(key, set()).add(snap.restaurant_id)
        return {
            "year": year,
            "month": month,
            "days_in_month": days_in_month,
            "first_weekday": first.weekday(),  # Mon=0..Sun=6
            "availability": {k: len(v) for k, v in buckets.items()},
        }

    @app.get("/api/calendar/day/{day}")
    def calendar_day(day: str):
        try:
            target = datetime.strptime(day, "%Y-%m-%d")
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        next_day = datetime(target.year, target.month, target.day, 23, 59, 59)
        with session_scope() as session:
            rows = session.execute(
                select(AvailabilitySnapshot, Restaurant)
                .join(
                    Restaurant,
                    Restaurant.id == AvailabilitySnapshot.restaurant_id,
                )
                .join(
                    Subscription,
                    Subscription.restaurant_id == AvailabilitySnapshot.restaurant_id,
                )
                .where(AvailabilitySnapshot.available == True)  # noqa: E712
                .where(AvailabilitySnapshot.slot_datetime >= target)
                .where(AvailabilitySnapshot.slot_datetime <= next_day)
                .distinct()
                .order_by(AvailabilitySnapshot.slot_datetime)
            ).all()
            seen = set()
            out = []
            for snap, r in rows:
                key = (r.id, snap.slot_datetime, snap.party_size)
                if key in seen:
                    continue
                seen.add(key)
                out.append(
                    {
                        "restaurant": {
                            "id": r.id,
                            "name": r.name,
                            "url": r.url,
                            "area": r.area,
                            "genre": r.genre,
                        },
                        "datetime": snap.slot_datetime.isoformat(),
                        "party_size": snap.party_size,
                        "price_jpy": snap.price_jpy,
                        "cancellation_policy": snap.cancellation_policy,
                    }
                )
            return out

    # ---------- settings ----------
    @app.get("/api/settings")
    def get_settings():
        c = service.config
        return {
            "poll_interval_seconds": c.app.poll_interval_seconds,
            "list_refresh_time": c.app.list_refresh_time,
            "smtp_host": c.email.smtp_host,
            "smtp_port": c.email.smtp_port,
            "smtp_user": c.email.smtp_user,
            "smtp_password": "" if c.email.smtp_password else "",
            "smtp_password_set": bool(c.email.smtp_password),
            "smtp_from": c.email.from_address,
            "smtp_use_starttls": c.email.use_starttls,
            "line_token": "",
            "line_token_set": bool(c.line.channel_access_token),
        }

    @app.put("/api/settings")
    def update_settings(payload: SettingsIn):
        c = service.config
        if payload.poll_interval_seconds is not None:
            service.set_poll_interval(payload.poll_interval_seconds)
        if payload.list_refresh_time is not None:
            c.app.list_refresh_time = payload.list_refresh_time
            service.reschedule_list_refresh(payload.list_refresh_time)
        if payload.smtp_host is not None:
            c.email.smtp_host = payload.smtp_host
        if payload.smtp_port is not None:
            c.email.smtp_port = payload.smtp_port
        if payload.smtp_user is not None:
            c.email.smtp_user = payload.smtp_user
        if payload.smtp_password is not None and payload.smtp_password != "":
            c.email.smtp_password = payload.smtp_password
        if payload.smtp_from is not None:
            c.email.from_address = payload.smtp_from
        if payload.smtp_use_starttls is not None:
            c.email.use_starttls = payload.smtp_use_starttls
        if payload.line_token is not None and payload.line_token != "":
            c.line.channel_access_token = payload.line_token
        c.save(default_config_path())
        return {"ok": True}

    # ---------- logs ----------
    @app.get("/api/logs")
    def list_logs(limit: int = 50):
        with session_scope() as session:
            rows = session.execute(
                select(NotificationLog, User, Restaurant)
                .join(User, User.id == NotificationLog.user_id)
                .join(Restaurant, Restaurant.id == NotificationLog.restaurant_id)
                .order_by(NotificationLog.id.desc())
                .limit(limit)
            ).all()
            return [
                {
                    "id": log.id,
                    "user": u.name,
                    "restaurant": r.name,
                    "channel": log.channel,
                    "slot_datetime": log.slot_datetime.isoformat(),
                    "party_size": log.party_size,
                    "sent_at": log.sent_at.isoformat(),
                    "success": log.success,
                    "error": log.error,
                }
                for log, u, r in rows
            ]

    return app
