from __future__ import annotations

import os
import time
from threading import Lock

_CACHE_TTL_SECONDS = max(1, int(os.getenv("PROFILE_CACHE_TTL_SECONDS", "300")))
_CACHE_MAX_ENTRIES = max(100, int(os.getenv("PROFILE_CACHE_MAX_ENTRIES", "1000")))

# {instructor_id: (expires_at_monotonic, display_name)}
_instructor_name_cache: dict[str, tuple[float, str]] = {}
_cache_lock = Lock()


def _prune_locked(now_monotonic: float) -> None:
    expired_keys = [
        key
        for key, (expires_at, _) in _instructor_name_cache.items()
        if expires_at <= now_monotonic
    ]
    for key in expired_keys:
        _instructor_name_cache.pop(key, None)

    while len(_instructor_name_cache) > _CACHE_MAX_ENTRIES:
        oldest_key = next(iter(_instructor_name_cache), None)
        if oldest_key is None:
            break
        _instructor_name_cache.pop(oldest_key, None)


def get_cached_instructor_name(instructor_id: str) -> str | None:
    key = str(instructor_id or "").strip()
    if not key:
        return None

    now_monotonic = time.monotonic()
    with _cache_lock:
        cached = _instructor_name_cache.get(key)
        if not cached:
            return None

        expires_at, value = cached
        if expires_at <= now_monotonic:
            _instructor_name_cache.pop(key, None)
            return None

        return value


def get_cached_instructor_names(instructor_ids: list[str]) -> dict[str, str]:
    now_monotonic = time.monotonic()
    result: dict[str, str] = {}

    with _cache_lock:
        _prune_locked(now_monotonic)
        for instructor_id in instructor_ids:
            key = str(instructor_id or "").strip()
            if not key:
                continue
            cached = _instructor_name_cache.get(key)
            if not cached:
                continue
            result[key] = cached[1]

    return result


def cache_instructor_name(instructor_id: str, display_name: str) -> None:
    key = str(instructor_id or "").strip()
    value = str(display_name or "").strip()
    if not key or not value:
        return

    now_monotonic = time.monotonic()
    expires_at = now_monotonic + _CACHE_TTL_SECONDS

    with _cache_lock:
        _prune_locked(now_monotonic)
        _instructor_name_cache[key] = (expires_at, value)


def cache_instructor_names(names_by_id: dict[str, str]) -> None:
    if not names_by_id:
        return

    now_monotonic = time.monotonic()
    expires_at = now_monotonic + _CACHE_TTL_SECONDS

    with _cache_lock:
        _prune_locked(now_monotonic)
        for instructor_id, display_name in names_by_id.items():
            key = str(instructor_id or "").strip()
            value = str(display_name or "").strip()
            if not key or not value:
                continue
            _instructor_name_cache[key] = (expires_at, value)
