"""Command parsing and execution for the admin terminal UI.

Each command is a function that returns a string (printed to the
terminal). Commands operate on the shared `Service` and database.
"""

from __future__ import annotations

import shlex
from typing import Callable

from sqlalchemy import select

from ..db import session_scope
from ..models import (
    NotificationLog,
    Restaurant,
    Subscription,
    User,
)
from ..service import Service

CommandFn = Callable[[Service, list[str]], str]

HELP_TEXT = """\
Available commands:

  help                                    Show this help
  status                                  Show service status
  start                                   Start polling
  stop                                    Stop polling
  interval <seconds>                      Set poll interval (>= 0.1s)

  refresh-list                            Refresh restaurant master list now

  users add <name> [--email=X] [--line=Y] [--off]
  users list
  users remove <user_id>
  users enable <user_id> | disable <user_id>

  restaurants list [keyword]              List (or search) restaurants
  restaurants show <restaurant_id>

  subscribe <user_id> <restaurant_id> [--email/--no-email] [--line/--no-line]
                                          [--min=N --max=M]
  subscriptions list [user_id]
  unsubscribe <subscription_id>

  logs [count]                            Show recent notification logs
  quit                                    Exit the admin UI (service stops)
"""


def execute(service: Service, raw: str) -> str:
    raw = raw.strip()
    if not raw:
        return ""
    try:
        parts = shlex.split(raw)
    except ValueError as exc:
        return f"parse error: {exc}"
    cmd, *rest = parts
    handler = COMMANDS.get(cmd)
    if not handler:
        return f"unknown command: {cmd!r}  (try 'help')"
    try:
        return handler(service, rest)
    except Exception as exc:  # noqa: BLE001
        return f"error: {exc}"


# -------- Commands --------

def cmd_help(_s: Service, _a: list[str]) -> str:
    return HELP_TEXT


def cmd_status(s: Service, _a: list[str]) -> str:
    state = "RUNNING" if s.running else "STOPPED"
    return (
        f"service: {state}\n"
        f"poll interval: {s.config.app.poll_interval_seconds:g}s\n"
        f"list refresh: daily at {s.config.app.list_refresh_time}\n"
        f"headless: {s.config.app.headless}\n"
    )


def cmd_start(s: Service, _a: list[str]) -> str:
    s.start()
    return "service started."


def cmd_stop(s: Service, _a: list[str]) -> str:
    s.stop()
    return "service stopped."


def cmd_interval(s: Service, args: list[str]) -> str:
    if len(args) != 1:
        return "usage: interval <seconds>"
    seconds = float(args[0])
    s.set_poll_interval(seconds)
    return f"interval set to {seconds:g}s."


def cmd_refresh_list(s: Service, _a: list[str]) -> str:
    n = s.refresh_restaurant_list()
    return f"refreshed: {n} restaurants."


# users -------------------------------------------------------------

def _parse_kv(args: list[str]) -> tuple[list[str], dict[str, str], set[str]]:
    positional, kv, flags = [], {}, set()
    for a in args:
        if a.startswith("--") and "=" in a:
            k, v = a[2:].split("=", 1)
            kv[k] = v
        elif a.startswith("--"):
            flags.add(a[2:])
        else:
            positional.append(a)
    return positional, kv, flags


def cmd_users(_s: Service, args: list[str]) -> str:
    if not args:
        return "usage: users <add|list|remove|enable|disable> ..."
    sub, *rest = args
    if sub == "list":
        with session_scope() as session:
            users = session.execute(select(User).order_by(User.id)).scalars().all()
            if not users:
                return "(no users)"
            lines = [f"{'ID':<4} {'NAME':<20} {'EMAIL':<30} {'LINE':<25} ENABLED"]
            for u in users:
                lines.append(
                    f"{u.id:<4} {u.name[:20]:<20} {(u.email or '-')[:30]:<30} "
                    f"{(u.line_user_id or '-')[:25]:<25} {u.enabled}"
                )
            return "\n".join(lines)
    if sub == "add":
        positional, kv, flags = _parse_kv(rest)
        if not positional:
            return "usage: users add <name> [--email=X] [--line=Y] [--off]"
        with session_scope() as session:
            u = User(
                name=positional[0],
                email=kv.get("email"),
                line_user_id=kv.get("line"),
                enabled="off" not in flags,
            )
            session.add(u)
            session.flush()
            return f"added user id={u.id}"
    if sub == "remove":
        if not rest:
            return "usage: users remove <user_id>"
        uid = int(rest[0])
        with session_scope() as session:
            u = session.get(User, uid)
            if not u:
                return f"no user id={uid}"
            session.delete(u)
            return f"removed user id={uid}"
    if sub in ("enable", "disable"):
        if not rest:
            return f"usage: users {sub} <user_id>"
        uid = int(rest[0])
        with session_scope() as session:
            u = session.get(User, uid)
            if not u:
                return f"no user id={uid}"
            u.enabled = sub == "enable"
            return f"user id={uid} enabled={u.enabled}"
    return f"unknown users subcommand: {sub}"


# restaurants -------------------------------------------------------

def cmd_restaurants(_s: Service, args: list[str]) -> str:
    if not args:
        return "usage: restaurants <list|show> ..."
    sub, *rest = args
    if sub == "list":
        keyword = rest[0] if rest else None
        with session_scope() as session:
            q = select(Restaurant).order_by(Restaurant.name)
            if keyword:
                q = q.where(Restaurant.name.ilike(f"%{keyword}%"))
            rs = session.execute(q).scalars().all()
            if not rs:
                return "(no restaurants. run 'refresh-list')"
            lines = [f"{'ID':<5} {'OMAKASE_ID':<20} NAME"]
            for r in rs:
                lines.append(f"{r.id:<5} {r.omakase_id[:20]:<20} {r.name}")
            return "\n".join(lines)
    if sub == "show":
        if not rest:
            return "usage: restaurants show <restaurant_id>"
        rid = int(rest[0])
        with session_scope() as session:
            r = session.get(Restaurant, rid)
            if not r:
                return f"no restaurant id={rid}"
            return (
                f"id: {r.id}\n"
                f"omakase_id: {r.omakase_id}\n"
                f"name: {r.name}\n"
                f"url: {r.url}\n"
                f"area: {r.area or '-'}\n"
                f"genre: {r.genre or '-'}\n"
            )
    return f"unknown restaurants subcommand: {sub}"


# subscriptions ----------------------------------------------------

def cmd_subscribe(_s: Service, args: list[str]) -> str:
    positional, kv, flags = _parse_kv(args)
    if len(positional) != 2:
        return (
            "usage: subscribe <user_id> <restaurant_id> "
            "[--email/--no-email] [--line/--no-line] [--min=N --max=M]"
        )
    user_id, restaurant_id = int(positional[0]), int(positional[1])
    with session_scope() as session:
        if not session.get(User, user_id):
            return f"no user id={user_id}"
        if not session.get(Restaurant, restaurant_id):
            return f"no restaurant id={restaurant_id}"
        sub = Subscription(
            user_id=user_id,
            restaurant_id=restaurant_id,
            notify_email="no-email" not in flags,
            notify_line="line" in flags,
            party_size_min=int(kv.get("min", "1")),
            party_size_max=int(kv.get("max", "8")),
        )
        session.add(sub)
        session.flush()
        return f"subscribed: id={sub.id}"


def cmd_subscriptions(_s: Service, args: list[str]) -> str:
    if args and args[0] == "list":
        args = args[1:]
    with session_scope() as session:
        q = select(Subscription).order_by(Subscription.id)
        if args:
            q = q.where(Subscription.user_id == int(args[0]))
        subs = session.execute(q).scalars().all()
        if not subs:
            return "(no subscriptions)"
        lines = [f"{'ID':<4} {'USER':<6} {'REST':<6} EMAIL LINE  MIN-MAX"]
        for s in subs:
            lines.append(
                f"{s.id:<4} {s.user_id:<6} {s.restaurant_id:<6} "
                f"{str(s.notify_email):<5} {str(s.notify_line):<5} "
                f"{s.party_size_min}-{s.party_size_max}"
            )
        return "\n".join(lines)


def cmd_unsubscribe(_s: Service, args: list[str]) -> str:
    if not args:
        return "usage: unsubscribe <subscription_id>"
    sid = int(args[0])
    with session_scope() as session:
        s = session.get(Subscription, sid)
        if not s:
            return f"no subscription id={sid}"
        session.delete(s)
        return f"removed subscription id={sid}"


def cmd_logs(_s: Service, args: list[str]) -> str:
    n = int(args[0]) if args else 20
    with session_scope() as session:
        rows = (
            session.execute(
                select(NotificationLog)
                .order_by(NotificationLog.id.desc())
                .limit(n)
            )
            .scalars()
            .all()
        )
        if not rows:
            return "(no notifications yet)"
        lines = []
        for r in rows:
            status = "OK" if r.success else f"ERR ({r.error or ''})"
            lines.append(
                f"[{r.sent_at:%Y-%m-%d %H:%M:%S}] u={r.user_id} r={r.restaurant_id} "
                f"{r.channel:<5} slot={r.slot_datetime:%Y-%m-%d %H:%M} "
                f"x{r.party_size} {status}"
            )
        return "\n".join(lines)


def cmd_quit(s: Service, _a: list[str]) -> str:
    s.stop()
    return "__QUIT__"


COMMANDS: dict[str, CommandFn] = {
    "help": cmd_help,
    "?": cmd_help,
    "status": cmd_status,
    "start": cmd_start,
    "stop": cmd_stop,
    "interval": cmd_interval,
    "refresh-list": cmd_refresh_list,
    "users": cmd_users,
    "restaurants": cmd_restaurants,
    "subscribe": cmd_subscribe,
    "subscriptions": cmd_subscriptions,
    "unsubscribe": cmd_unsubscribe,
    "logs": cmd_logs,
    "quit": cmd_quit,
    "exit": cmd_quit,
}
