"""Muzikk application entry point."""

from __future__ import annotations

import logging
import logging.handlers
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .api import api_router
from .config import get_env_config
from .db import init_db, session_scope
from .jobs.runner import worker
from .schemas import HealthOut
from .services import mode as mode_service
from .services import settings as settings_service

logger = logging.getLogger(__name__)

env = get_env_config()


def configure_logging() -> None:
    # .env values often carry a stray trailing space.
    level = getattr(logging, env.log_level.strip().upper(), logging.INFO)
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)-7s [%(name)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    root.addHandler(console)

    try:
        env.log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            env.log_dir / "muzikk.log", maxBytes=5_000_000, backupCount=3, encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
    except OSError as exc:
        logger.warning("File logging disabled: %s", exc)

    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("multipart").setLevel(logging.WARNING)


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    logger.info("Starting Muzikk %s", __version__)
    init_db()
    await worker.start()
    try:
        yield
    finally:
        logger.info("Stopping Muzikk")
        await worker.stop()


app = FastAPI(
    title="Muzikk",
    version=__version__,
    description="Self-hosted music request and download manager",
    lifespan=lifespan,
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    redoc_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)


@app.get("/api/health", response_model=HealthOut, tags=["system"])
async def health() -> HealthOut:
    with session_scope() as session:
        general = settings_service.load(session, "general")
        active_mode = mode_service.current(session)
        jellyfin = settings_service.load(session, "jellyfin")
        musicbrainz = settings_service.load(session, "musicbrainz")
        slskd = settings_service.load(session, "slskd")
        prowlarr = settings_service.load(session, "prowlarr")
        qbittorrent = settings_service.load(session, "qbittorrent")

    services = {
        "musicbrainz": bool(musicbrainz.url or musicbrainz.use_public_fallback),
        "slskd": bool(slskd.enabled and slskd.url and slskd.api_key),
        "prowlarr": bool(prowlarr.enabled and prowlarr.url and prowlarr.api_key),
        "qbittorrent": bool(qbittorrent.enabled and qbittorrent.url),
    }
    # Reporting a service this installation was never built on would only make
    # the dashboard look broken.
    if active_mode != mode_service.LOCAL:
        services["jellyfin"] = bool(jellyfin.url and jellyfin.api_key)

    return HealthOut(
        status="ok",
        version=__version__,
        setup_required=not general.setup_completed,
        mode=active_mode,
        services=services,
    )


static_dir = Path(env.static_dir)
assets_dir = static_dir / "assets"

if assets_dir.is_dir():
    app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")


@app.get("/{full_path:path}", include_in_schema=False)
async def spa(full_path: str, request: Request):
    """Serve the built SPA, letting the router handle client side paths."""
    if full_path.startswith("api/"):
        return JSONResponse({"detail": "Not found"}, status_code=404)

    if full_path:
        candidate = (static_dir / full_path).resolve()
        try:
            candidate.relative_to(static_dir.resolve())
        except ValueError:
            return JSONResponse({"detail": "Not found"}, status_code=404)
        if candidate.is_file():
            return FileResponse(candidate)

    index = static_dir / "index.html"
    if index.is_file():
        return FileResponse(index)
    return JSONResponse(
        {
            "detail": "The web interface is not built. Run the Docker build or "
            "`npm run build` in the frontend folder."
        },
        status_code=503,
    )
