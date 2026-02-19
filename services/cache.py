"""
Simple file-based cache with TTL support.
"""

import json
import os
import time
import hashlib
import threading

import config

_lock = threading.Lock()


def _cache_path(key: str) -> str:
    safe = hashlib.md5(key.encode()).hexdigest()
    return os.path.join(config.CACHE_DIR, f"{safe}.json")


def get(key: str, ttl: int | None = None) -> dict | list | None:
    """Return cached value if it exists and hasn't expired."""
    if ttl is None:
        ttl = config.CACHE_TTL_SECONDS
    path = _cache_path(key)
    try:
        with _lock:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        if time.time() - data.get("ts", 0) < ttl:
            return data["value"]
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        pass
    return None


def set(key: str, value) -> None:
    """Store a value in cache."""
    os.makedirs(config.CACHE_DIR, exist_ok=True)
    path = _cache_path(key)
    with _lock:
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"ts": time.time(), "value": value}, f, ensure_ascii=False)


def get_or_fetch(key: str, fetch_fn, ttl: int | None = None):
    """Return cached value or call fetch_fn and cache the result."""
    cached = get(key, ttl)
    if cached is not None:
        return cached
    value = fetch_fn()
    if value is not None:
        set(key, value)
    return value
