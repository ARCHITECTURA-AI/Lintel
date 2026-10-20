"""FastAPI application factory."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import errors
from .config import get_settings
from .routers import applications, auth, discovery, insights, profile, runner, tasks


def create_app() -> FastAPI:
    settings = get_settings()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        stop = None
        if os.environ.get("LINTEL_EMBEDDED_WORKER", "1" if settings.env == "development" else "0") == "1":
            from .worker import start_background

            stop = start_background()
        yield
        if stop is not None:
            stop.set()

    app = FastAPI(
        title="Lintel API",
        version="0.1.0",
        description="The agent prepares, you sign off. Ledger, drafting, approvals and audit.",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.web_origin],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    errors.install(app)
    for r in (auth.router, profile.router, discovery.router, applications.router, tasks.router, runner.router, insights.router):
        app.include_router(r)

    @app.get("/health")
    def health() -> dict:
        return {"ok": True}

    return app


app = create_app()
