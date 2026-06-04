from __future__ import annotations

import copy
import os
import time
from threading import Lock

_CACHE_TTL_SECONDS = max(0, int(os.getenv("ASSIGNED_EXAMS_CACHE_TTL_SECONDS", "20")))
_CACHE_MAX_ENTRIES = max(100, int(os.getenv("ASSIGNED_EXAMS_CACHE_MAX_ENTRIES", "1500")))

# {(student_id, limit, offset): (expires_at_monotonic, payload_dict)}
_assigned_exams_cache: dict[tuple[str, int, int], tuple[float, dict]] = {}
_cache_lock = Lock()


def _cache_enabled() -> bool:
    return _CACHE_TTL_SECONDS > 0


def _prune_locked(now_monotonic: float) -> None:
    expired_keys = [
        key
        for key, (expires_at, _) in _assigned_exams_cache.items()
        if expires_at <= now_monotonic
    ]
    for key in expired_keys:
        _assigned_exams_cache.pop(key, None)

    while len(_assigned_exams_cache) > _CACHE_MAX_ENTRIES:
        oldest_key = next(iter(_assigned_exams_cache), None)
        if oldest_key is None:
            break
        _assigned_exams_cache.pop(oldest_key, None)


def _build_key(student_id: str, limit: int, offset: int) -> tuple[str, int, int]:
    return (str(student_id or "").strip(), int(limit), int(offset))


def get_assigned_exams_cache(student_id: str, limit: int, offset: int) -> dict | None:
    if not _cache_enabled():
        return None

    key = _build_key(student_id, limit, offset)
    now_monotonic = time.monotonic()

    with _cache_lock:
        cached = _assigned_exams_cache.get(key)
        if not cached:
            return None

        expires_at, payload = cached
        if expires_at <= now_monotonic:
            _assigned_exams_cache.pop(key, None)
            return None

        return copy.deepcopy(payload)


def set_assigned_exams_cache(student_id: str, limit: int, offset: int, payload: dict) -> None:
    if not _cache_enabled():
        return

    key = _build_key(student_id, limit, offset)
    now_monotonic = time.monotonic()
    expires_at = now_monotonic + _CACHE_TTL_SECONDS

    with _cache_lock:
        _prune_locked(now_monotonic)
        _assigned_exams_cache[key] = (expires_at, copy.deepcopy(payload))


def invalidate_assigned_exams_cache_for_student(student_id: str) -> None:
    key_student = str(student_id or "").strip()
    if not key_student:
        return

    with _cache_lock:
        keys_to_remove = [
            cache_key
            for cache_key in _assigned_exams_cache.keys()
            if cache_key[0] == key_student
        ]
        for cache_key in keys_to_remove:
            _assigned_exams_cache.pop(cache_key, None)
