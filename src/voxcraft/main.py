"""VoxCraft FastAPI 入口。"""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

import structlog
from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from voxcraft.api import admin, business, events, health, jobs, models_library
from voxcraft.api.error_handlers import register_error_handlers
from voxcraft.config import get_settings
from voxcraft.db.bootstrap import scan_existing_models, seed_default_providers
from voxcraft.db.engine import get_engine
from voxcraft.db.migrate import run_upgrade_head
from voxcraft.events.bus import get_bus
from voxcraft.logging import setup_logging
from voxcraft.models_lib.service import ModelDownloadService
from voxcraft.runtime.lru import LruOne
from voxcraft.runtime.scheduler import Scheduler


log = structlog.get_logger()

# 生产构建时复制到此路径；开发不存在则走 Vite dev server
_STATIC_DIR = Path("/app/static")


@asynccontextmanager
async def lifespan(app: FastAPI):
    run_upgrade_head()
    engine = get_engine()
    inserted = seed_default_providers(engine)
    manual_scanned = scan_existing_models(engine)
    bus = get_bus()
    app.state.event_bus = bus
    app.state.scheduler = Scheduler(bus=bus)
    app.state.lru = LruOne(bus=bus)

    settings = get_settings()
    download_svc = ModelDownloadService(
        engine=engine, bus=bus, models_dir=settings.models_dir
    )
    orphans = download_svc.startup_cleanup()
    app.state.model_download_service = download_svc

    log.info(
        "voxcraft.startup",
        seeded_providers=inserted,
        manual_models_scanned=manual_scanned,
        orphan_downloads_cleaned=orphans,
    )
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    setup_logging(settings.log_level)

    app = FastAPI(title="VoxCraft", version="0.1.0", lifespan=lifespan)

    register_error_handlers(app)

    app.include_router(health.router)
    app.include_router(admin.router)
    app.include_router(jobs.router)
    app.include_router(business.router)
    app.include_router(events.router)
    app.include_router(models_library.router)

    if _STATIC_DIR.exists():
        app.mount("/ui", StaticFiles(directory=_STATIC_DIR, html=True), name="ui")

        @app.get("/", include_in_schema=False)
        def _root():
            return RedirectResponse(url="/ui/")

    return app


app = create_app()
