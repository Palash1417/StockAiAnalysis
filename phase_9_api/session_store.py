"""Session store — Protocol + SQLiteSessionStore (dev) + RedisSessionStore (prod).

SQLiteSessionStore is the default for dev/test; no external deps needed.
RedisSessionStore requires `redis` package and a running Redis instance.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from typing import Protocol, runtime_checkable

from .models import Thread

_TTL_SECONDS = 86400   # 24 h


@runtime_checkable
class SessionStore(Protocol):
    def get(self, thread_id: str) -> Thread | None: ...
    def save(self, thread: Thread) -> None: ...
    def delete(self, thread_id: str) -> None: ...
    def list_all(self) -> list[Thread]: ...


# ---------------------------------------------------------------------------
# SQLite (dev / test)
# ---------------------------------------------------------------------------

class SQLiteSessionStore:
    """Thread-safe SQLite-backed session store.

    Uses a single connection protected by a threading.Lock.
    Expired rows are purged lazily on each read/list call.
    """

    def __init__(self, db_path: str = ":memory:", ttl_seconds: int = _TTL_SECONDS):
        self._db_path = db_path
        self._ttl = ttl_seconds
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    thread_id  TEXT PRIMARY KEY,
                    data       TEXT NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
            self._conn.commit()

    def _purge_expired(self) -> None:
        cutoff = time.time() - self._ttl
        self._conn.execute("DELETE FROM sessions WHERE updated_at < ?", (cutoff,))
        self._conn.commit()

    def get(self, thread_id: str) -> Thread | None:
        with self._lock:
            self._purge_expired()
            row = self._conn.execute(
                "SELECT data FROM sessions WHERE thread_id = ?", (thread_id,)
            ).fetchone()
        if row is None:
            return None
        return Thread.model_validate(json.loads(row[0]))

    def save(self, thread: Thread) -> None:
        data = thread.model_dump_json()
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO sessions (thread_id, data, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(thread_id) DO UPDATE SET data = excluded.data,
                                                      updated_at = excluded.updated_at
                """,
                (thread.thread_id, data, time.time()),
            )
            self._conn.commit()

    def delete(self, thread_id: str) -> None:
        with self._lock:
            self._conn.execute(
                "DELETE FROM sessions WHERE thread_id = ?", (thread_id,)
            )
            self._conn.commit()

    def list_all(self) -> list[Thread]:
        with self._lock:
            self._purge_expired()
            rows = self._conn.execute(
                "SELECT data FROM sessions ORDER BY updated_at DESC"
            ).fetchall()
        return [Thread.model_validate(json.loads(r[0])) for r in rows]


# ---------------------------------------------------------------------------
# Redis (prod)
# ---------------------------------------------------------------------------

class RedisSessionStore:
    """Redis-backed session store with per-key TTL.

    Requires `redis` package: `pip install redis`.
    `url` is the Redis connection string, e.g. ``redis://localhost:6379``.
    """

    def __init__(self, url: str = "redis://localhost:6379", ttl_seconds: int = _TTL_SECONDS):
        import redis  # type: ignore
        self._r = redis.from_url(url, decode_responses=True)
        self._ttl = ttl_seconds
        self._prefix = "mfrag:thread:"

    def _key(self, thread_id: str) -> str:
        return f"{self._prefix}{thread_id}"

    def get(self, thread_id: str) -> Thread | None:
        raw = self._r.get(self._key(thread_id))
        if raw is None:
            return None
        return Thread.model_validate(json.loads(raw))

    def save(self, thread: Thread) -> None:
        self._r.set(self._key(thread.thread_id), thread.model_dump_json(), ex=self._ttl)

    def delete(self, thread_id: str) -> None:
        self._r.delete(self._key(thread_id))

    def list_all(self) -> list[Thread]:
        keys = self._r.keys(f"{self._prefix}*")
        threads = []
        for key in keys:
            raw = self._r.get(key)
            if raw:
                threads.append(Thread.model_validate(json.loads(raw)))
        threads.sort(key=lambda t: t.created_at, reverse=True)
        return threads


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def build_session_store(config: dict) -> SessionStore:
    backend = config.get("backend", "sqlite")
    if backend == "redis":
        url = config.get("redis", {}).get("url", "redis://localhost:6379")
        ttl = int(config.get("redis", {}).get("ttl_seconds", _TTL_SECONDS))
        return RedisSessionStore(url=url, ttl_seconds=ttl)
    # default: sqlite
    path = config.get("sqlite", {}).get("path", ":memory:")
    ttl = int(config.get("sqlite", {}).get("ttl_hours", 24)) * 3600
    return SQLiteSessionStore(db_path=path, ttl_seconds=ttl)
