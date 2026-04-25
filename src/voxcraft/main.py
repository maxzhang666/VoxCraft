"""VoxCraft FastAPI 入口。"""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

import structlog
from fastapi import FastAPI
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from voxcraft.api import (
    admin,
    admin_llm,
    admin_settings,
    business,
    events,
    health,
    jobs,
    models_library,
    oai_compat,
    video_translate,
    voices,
)
from voxcraft.api.error_handlers import register_error_handlers
from voxcraft.config import get_settings
from voxcraft.db.bootstrap import scan_existing_models
from voxcraft.db.engine import get_engine
from voxcraft.db.migrate import run_upgrade_head
from voxcraft.events.bus import get_bus
from voxcraft.logging import setup_logging
from voxcraft.models_lib.service import ModelDownloadService
from voxcraft.runtime.lru import LruOne
from voxcraft.runtime.pool_scheduler import PoolScheduler
from voxcraft.runtime.proxy import reload_proxy_from_db
from voxcraft.runtime.scheduler import InProcessScheduler


log = structlog.get_logger()

# 生产构建时复制到此路径；开发不存在则走 Vite dev server
_STATIC_DIR = Path("/app/static")


@asynccontextmanager
async def lifespan(app: FastAPI):
    run_upgrade_head()
    engine = get_engine()
    # 代理注入要早于任何后续可能触发模型下载/HTTP 请求的步骤
    proxy_active = reload_proxy_from_db(engine)
    manual_scanned = scan_existing_models(engine)
    bus = get_bus()
    settings = get_settings()

    app.state.event_bus = bus

    # Scheduler backend 按配置实例化（ADR-013）
    # - pool: worker 子进程 + 真取消（生产推荐）
    # - inprocess: 当前主进程 asyncio 执行（默认；测试友好）
    if settings.scheduler_backend == "pool":
        scheduler = PoolScheduler(bus=bus)
        await scheduler.start()
        app.state.scheduler = scheduler
    else:
        app.state.scheduler = InProcessScheduler(bus=bus)

    # admin.test_provider 仍使用 app.state.lru 做探活；与 scheduler 内 LRU 是不同实例。
    # 两处 LRU 不同步的代价：探活加载的模型不会被推理路径复用（下次推理会重新加载）。
    # 权衡：探活是偶发人工动作，不值得为此让探活穿透 scheduler 接口（侵入性大）。
    app.state.lru = LruOne(bus=bus)

    download_svc = ModelDownloadService(
        engine=engine, bus=bus, models_dir=settings.models_dir
    )
    orphans = download_svc.startup_cleanup()
    app.state.model_download_service = download_svc

    log.info(
        "voxcraft.startup",
        manual_models_scanned=manual_scanned,
        orphan_downloads_cleaned=orphans,
        scheduler_backend=settings.scheduler_backend,
        proxy_hf_endpoint=proxy_active.get("hf_endpoint") or None,
        proxy_https=bool(proxy_active.get("https_proxy")),
    )
    try:
        yield
    finally:
        await app.state.scheduler.shutdown()


def create_app() -> FastAPI:
    settings = get_settings()
    setup_logging(settings.log_level)

    app = FastAPI(title="VoxCraft", version="0.1.0", lifespan=lifespan)

    register_error_handlers(app)

    # 统一 /api 前缀挂载全部业务 / 管理 / SSE / 模型库路由；
    # OpenAI 兼容层 /v1/audio/* 是规范路径，不加前缀。
    app.include_router(health.router, prefix="/api")
    app.include_router(admin.router, prefix="/api")
    app.include_router(admin_llm.router, prefix="/api")
    app.include_router(admin_settings.router, prefix="/api")
    app.include_router(jobs.router, prefix="/api")
    app.include_router(business.router, prefix="/api")
    app.include_router(voices.router, prefix="/api")
    app.include_router(video_translate.router, prefix="/api")
    app.include_router(events.router, prefix="/api")
    app.include_router(models_library.router, prefix="/api")
    app.include_router(oai_compat.router)

    if _STATIC_DIR.exists():
        # 哈希命名资源走 StaticFiles（强缓存），其他 /ui/* 落到通用 handler：
        # - 真实存在的文件（public/ 里的 icon 等）正常返回
        # - 其他路径（SPA deep-link 刷新、未知路径）返回 index.html 让前端 Router 接管
        assets_dir = _STATIC_DIR / "assets"
        if assets_dir.exists():
            app.mount(
                "/ui/assets",
                StaticFiles(directory=assets_dir),
                name="ui-assets",
            )

        _index_html = _STATIC_DIR / "index.html"

        @app.get("/ui", include_in_schema=False)
        @app.get("/ui/{full_path:path}", include_in_schema=False)
        async def _spa(full_path: str = ""):
            if full_path:
                candidate = _STATIC_DIR / full_path
                if candidate.is_file():
                    return FileResponse(candidate)
            return FileResponse(_index_html)

        @app.get("/", include_in_schema=False)
        def _root():
            return RedirectResponse(url="/ui/")

    return app


app = create_app()
