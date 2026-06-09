"""FastAPI application entrypoint (PRODUCTION READY)."""

from __future__ import annotations

import traceback
import logging
import sys
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from backend.core.config import get_settings
from backend.core.errors import register_exception_handlers
from backend.models.database import init_db

logger = logging.getLogger(__name__)

# ---------------- PATH SETUP ----------------
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ---------------- LIFESPAN ----------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    App startup lifecycle.
    Safe for Neon + Render deployment.
    """
    settings = get_settings()
    settings.ensure_directories()

    # Initialize DB tables (Neon-safe)
    init_db()

    yield


# ---------------- APP FACTORY ----------------
def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="CodeOrbit REST API",
        lifespan=lifespan,
    )

    # ---------------- CORS ----------------
    app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    )

    # ---------------- ERROR HANDLERS ----------------
    register_exception_handlers(app)

    # ---------------- ROUTERS ----------------
    from backend.api.routes_repository import router as repository_router
    from backend.api.routes_query import router as query_router
    from backend.api.routes_chat import router as chat_router

    app.include_router(repository_router)
    app.include_router(query_router)
    app.include_router(chat_router)

    # ---------------- HEALTH CHECK ----------------
    @app.get("/health")
    def health():
        return {
            "status": "ok",
            "service": settings.app_name,
            "version": settings.app_version,
        }

    return app


# ---------------- APP INSTANCE ----------------
app = create_app()


# ---------------- ROOT ----------------
@app.get("/")
def root():
    return {"status": "CodeOrbit API running"}


# ---------------- GLOBAL ERROR HANDLER ----------------
@app.exception_handler(Exception)
async def global_error_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={
            "error": "internal_error",
            "message": str(exc),
            "trace": traceback.format_exc(),
        },
    )