"""Postgres-backed CorpusPointer — §5.9 atomic swap.

Two tables:
  * `corpus_pointer`  — a single row (`id = 1`) whose `live` column holds
    the currently-serving corpus_version. Flipping that one column IS the
    swap.
  * `corpus_history`  — every corpus_version that has ever been live. Used
    for GC (`keep_versions`).
"""
from __future__ import annotations

from typing import Any, Callable


class PgCorpusPointer:
    def __init__(self, connect: Callable[[], Any]):
        self._connect = connect

    def get_live(self) -> str | None:
        sql = "SELECT live FROM corpus_pointer WHERE id = 1"
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(sql)
            row = cur.fetchone()
            return row[0] if row else None

    def set_live(self, corpus_version: str) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO corpus_history (corpus_version) VALUES (%s)
                ON CONFLICT (corpus_version) DO NOTHING
                """,
                (corpus_version,),
            )
            cur.execute(
                """
                UPDATE corpus_pointer
                   SET live = %s, updated_at = NOW()
                 WHERE id = 1
                """,
                (corpus_version,),
            )

    def history(self) -> list[str]:
        sql = """
            SELECT corpus_version FROM corpus_history ORDER BY created_at ASC
        """
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(sql)
            return [row[0] for row in cur.fetchall()]
