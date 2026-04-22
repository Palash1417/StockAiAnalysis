"""Composition root — wires the prod backends into phase 4.1's interfaces.

Everything here is glue. The adapters don't know about each other; this
module is responsible for creating the connection factory, instantiating
each adapter, and returning the bundle the ingestion pipeline needs.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any, Callable

import yaml

from .adapters import (
    PgBM25Index,
    PgCorpusPointer,
    PgEmbeddingCache,
    PgFactKV,
    PgVectorIndex,
    S3Storage,
)
from .smoke import build_smoke_runner


_ENV_VAR_RE = re.compile(r"\$\{([A-Z0-9_]+)(?::([^}]*))?\}")


def load_config(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return _expand_env(raw)


def _expand_env(obj):
    if isinstance(obj, dict):
        return {k: _expand_env(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_expand_env(v) for v in obj]
    if isinstance(obj, str):
        def sub(m):
            name, default = m.group(1), m.group(2) or ""
            return os.environ.get(name, default)
        return _ENV_VAR_RE.sub(sub, obj)
    return obj


@dataclass
class ProdPipeline:
    vector_index: PgVectorIndex
    bm25_index: PgBM25Index
    fact_kv: PgFactKV
    embedding_cache: PgEmbeddingCache
    corpus_pointer: PgCorpusPointer
    storage: S3Storage
    smoke_runner: Callable
    connect: Callable[[], Any]
    config: dict


def build_prod_pipeline(
    config_path: str,
    *,
    connect: Callable[[], Any] | None = None,
    s3_client: Any | None = None,
) -> ProdPipeline:
    """Builds a ProdPipeline from a yaml config.

    `connect` and `s3_client` are optional injection points for tests. In
    prod, leave them unset and the defaults (`psycopg.connect` + `boto3`)
    are used.
    """
    config = load_config(config_path)

    if connect is None:
        connect = _default_pg_connect(config["postgres"])

    vector_index = PgVectorIndex(connect)
    bm25_index = PgBM25Index(connect)
    fact_kv = PgFactKV(connect)
    embedding_cache = PgEmbeddingCache(connect)
    corpus_pointer = PgCorpusPointer(connect)

    s3cfg = config.get("s3", {})
    storage = S3Storage(
        bucket=s3cfg["bucket"],
        endpoint_url=s3cfg.get("endpoint_url") or None,
        region=s3cfg.get("region") or None,
        client=s3_client,
    )

    smoke_runner = build_smoke_runner(
        config.get("smoke", {}), vector_index, fact_kv,
    )

    return ProdPipeline(
        vector_index=vector_index,
        bm25_index=bm25_index,
        fact_kv=fact_kv,
        embedding_cache=embedding_cache,
        corpus_pointer=corpus_pointer,
        storage=storage,
        smoke_runner=smoke_runner,
        connect=connect,
        config=config,
    )


def _default_pg_connect(pg_cfg: dict) -> Callable[[], Any]:
    dsn = pg_cfg["dsn"]
    app_name = pg_cfg.get("application_name")
    stmt_timeout = pg_cfg.get("statement_timeout_ms")

    def connect():
        import psycopg  # lazy

        options_parts = []
        if stmt_timeout:
            options_parts.append(f"-c statement_timeout={int(stmt_timeout)}")
        kwargs: dict[str, Any] = {"autocommit": True}
        if app_name:
            kwargs["application_name"] = app_name
        if options_parts:
            kwargs["options"] = " ".join(options_parts)
        return psycopg.connect(dsn, **kwargs)

    return connect
