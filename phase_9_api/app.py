"""FastAPI application factory.

Usage:
    uvicorn phase_9_api.app:create_app --factory --reload
    # or pass config path:
    CONFIG_PATH=config/api.yaml uvicorn phase_9_api.app:create_app --factory
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

load_dotenv(Path(__file__).parent.parent / ".env")

from .pipeline import build_pipeline
from .rate_limiter import RateLimitMiddleware
from .router import router
from .session_store import build_session_store
from .thread_manager import ThreadManager


def _load_config(path: str | None = None) -> dict[str, Any]:
    config_path = path or os.environ.get(
        "CONFIG_PATH",
        str(Path(__file__).parent / "config" / "api.yaml"),
    )
    return yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))


def create_app(config: dict[str, Any] | None = None) -> FastAPI:
    """Application factory — build and return a configured FastAPI instance."""
    if config is None:
        config = _load_config()

    # --- Lifespan: initialise heavy state once on startup ---
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        store = build_session_store(config.get("session_store", {}))
        app.state.thread_manager = ThreadManager(store=store)
        app.state.pipeline = build_pipeline(config)
        yield
        # No explicit cleanup needed for in-memory / SQLite stores

    app = FastAPI(
        title="Mutual Fund FAQ Assistant",
        description="Facts-only RAG assistant for mutual fund scheme queries.",
        version="0.1.0",
        lifespan=lifespan,
    )

    # --- Middleware ---
    # Merge static config origins with CORS_ORIGINS env var (set on Render
    # to the Vercel deployment URL, e.g. https://xxx.vercel.app)
    env_origins = [
        o.strip()
        for o in os.environ.get("CORS_ORIGINS", "").split(",")
        if o.strip()
    ]
    origins = config.get("cors", {}).get("origins", []) + env_origins
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins or ["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    rate_cfg = config.get("rate_limit", {})
    app.add_middleware(
        RateLimitMiddleware,
        max_requests=rate_cfg.get("max_requests", 20),
        window_seconds=rate_cfg.get("window_seconds", 60),
    )

    # --- Routes ---
    app.include_router(router)

    return app
