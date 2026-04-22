"""Postgres-backed FactKVStore — exact-lookup fast path (§5.8).

`get()` returns the exact shape the in-memory reference implementation does
(`{"value", "source_url", "last_updated"}`) so callers stay backend-agnostic.
"""
from __future__ import annotations

from typing import Any, Callable


class PgFactKV:
    def __init__(self, connect: Callable[[], Any]):
        self._connect = connect

    def put(
        self,
        scheme_id: str,
        field_name: str,
        value: str,
        source_url: str,
        last_updated: str,
    ) -> None:
        sql = """
            INSERT INTO fact_kv
                (scheme_id, field_name, value, source_url, last_updated, updated_at)
            VALUES (%s, %s, %s, %s, %s, NOW())
            ON CONFLICT (scheme_id, field_name) DO UPDATE SET
                value        = EXCLUDED.value,
                source_url   = EXCLUDED.source_url,
                last_updated = EXCLUDED.last_updated,
                updated_at   = NOW()
        """
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                sql, (scheme_id, field_name, value, source_url, last_updated)
            )

    def get(self, scheme_id: str, field_name: str) -> dict | None:
        sql = """
            SELECT value, source_url, last_updated
              FROM fact_kv
             WHERE scheme_id = %s AND field_name = %s
        """
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(sql, (scheme_id, field_name))
            row = cur.fetchone()
            if row is None:
                return None
            return {
                "value": row[0],
                "source_url": row[1],
                "last_updated": row[2],
            }
