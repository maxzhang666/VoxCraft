"""ModelDownloadService：下载任务调度 + SSE 进度 + 软取消 + 孤儿清理。

并发模型：
- 每次 enqueue 创建 asyncio.Task 跑 _run(model_id)
- _run 内部 `async with self._lock` 自动 FIFO 排队（asyncio.Lock 公平等待）
- 阻塞下载通过 `loop.run_in_executor` 跑线程池，避免阻塞事件循环
- 进度扫描 asyncio.Task 每秒 du -s 目标目录 → SSE

取消：
- 软取消：标 DB cancelled；等待中任务出队跳过；进行中任务设 cancel 标记，
  底层阻塞 IO 无法立即中止，但 DB 状态立即更新让 UI 反映
"""
from __future__ import annotations

import asyncio
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import Engine
from sqlmodel import Session, select

from voxcraft.db.models import Model
from voxcraft.errors import DownloadError, VoxCraftError
from voxcraft.events.bus import Event, EventBus
from voxcraft.models_lib.catalog import get_by_key
from voxcraft.models_lib.downloader import (
    download_hf,
    download_ms,
    download_torch_hub,
    download_url,
)


_SCAN_INTERVAL = 1.0  # 秒


class ModelDownloadService:
    def __init__(
        self,
        engine: Engine,
        bus: EventBus,
        models_dir: Path,
    ) -> None:
        self._engine = engine
        self._bus = bus
        self._models_dir = Path(models_dir)
        self._lock = asyncio.Lock()
        self._waiting: list[int] = []       # model_ids 排队未进锁
        self._running: int | None = None    # 当前执行
        self._cancels: set[int] = set()     # 收到取消请求的 model_id
        self._tasks: set[asyncio.Task] = set()

    # --- 公共 API -----------------------------------------------------

    async def enqueue(
        self,
        *,
        catalog_key: str,
        source: str,
        repo_id: str,
        kind: str,
    ) -> int:
        """创建 Model 行（pending）+ 启动后台 _run task。返回 model_id。"""
        now = datetime.now(UTC)
        with Session(self._engine) as s:
            m = Model(
                catalog_key=catalog_key,
                source=source,
                repo_id=repo_id,
                kind=kind,
                status="pending",
                progress=0.0,
                created_at=now,
                updated_at=now,
            )
            s.add(m)
            s.commit()
            s.refresh(m)
            model_id = m.id
        assert model_id is not None
        task = asyncio.create_task(self._run(model_id))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return model_id

    def queue_position(self, model_id: int) -> int | None:
        """0 = 正在跑；1+ = 排队位置；None = 不在队列。"""
        if self._running == model_id:
            return 0
        try:
            return self._waiting.index(model_id) + 1
        except ValueError:
            return None

    async def cancel(self, model_id: int) -> None:
        """软取消：标 DB cancelled；如等待中从队列移除；如正在跑设 flag。"""
        self._cancels.add(model_id)
        if model_id in self._waiting:
            self._waiting.remove(model_id)
        self._update_status(
            model_id,
            status="cancelled",
            progress=0.0,
            finished=True,
        )
        await self._publish("model_download_failed", model_id, extra={"cancelled": True})

    async def wait_idle(self) -> None:
        """测试辅助：等所有 task 完成。"""
        if self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    def startup_cleanup(self) -> int:
        """服务启动时扫描 `status=downloading` 孤儿，改 failed + 删磁盘半成品。"""
        cleaned = 0
        with Session(self._engine) as s:
            orphans = s.exec(
                select(Model).where(Model.status == "downloading")
            ).all()
            for m in orphans:
                if m.local_path:
                    p = Path(m.local_path)
                    if p.exists():
                        shutil.rmtree(p, ignore_errors=True)
                m.status = "failed"
                m.error_code = "ORPHAN_ON_STARTUP"
                m.error_message = "Process crashed during download; cleaned on restart."
                m.finished_at = datetime.now(UTC)
                m.updated_at = datetime.now(UTC)
                s.add(m)
                cleaned += 1
            s.commit()
        return cleaned

    # --- 内部流程 ------------------------------------------------------

    async def _run(self, model_id: int) -> None:
        self._waiting.append(model_id)
        try:
            async with self._lock:
                # 从等待队列移出
                if model_id in self._waiting:
                    self._waiting.remove(model_id)

                # 已被取消 → 直接跳过
                if model_id in self._cancels:
                    self._cancels.discard(model_id)
                    return

                self._running = model_id
                try:
                    await self._do_download(model_id)
                finally:
                    self._running = None
        except Exception:  # 最后的兜底，避免异常淹没
            pass

    async def _do_download(self, model_id: int) -> None:
        # UI 改完代理未重启场景：每次下载前从 DB 重新加载并注入 env
        # 注入是 process 全局；同进程后续 huggingface_hub / httpx 调用立即生效
        from voxcraft.runtime.proxy import reload_proxy_from_db
        reload_proxy_from_db(self._engine)

        model = self._load_model(model_id)
        target = self._models_dir / model.catalog_key
        # 从 catalog 取预期总大小（用于进度估算）；custom 模型无 catalog 则 None
        entry = get_by_key(model.catalog_key)
        expected_bytes = entry.size_mb * 1024 * 1024 if entry else None

        self._update_status(
            model_id,
            status="downloading",
            progress=0.01,   # 立即显示 1% 让 UI 有反馈
            local_path=str(target),
            started=True,
        )

        scan_task = asyncio.create_task(
            self._watch_progress(model_id, target, expected_bytes)
        )
        loop = asyncio.get_running_loop()

        try:
            if model.source == "hf":
                await loop.run_in_executor(
                    None, download_hf, model.repo_id, target
                )
            elif model.source == "ms":
                await loop.run_in_executor(
                    None, download_ms, model.repo_id, target
                )
            elif model.source == "url":
                file_path = target / Path(model.repo_id).name if "/" in model.repo_id else target
                await loop.run_in_executor(
                    None, download_url, model.repo_id, file_path
                )
            elif model.source == "torch_hub":
                await loop.run_in_executor(
                    None, download_torch_hub, model.repo_id, target
                )
            else:
                raise DownloadError(
                    f"Unknown source: {model.source}",
                    details={"model_id": model_id},
                )
        except Exception as e:
            scan_task.cancel()
            self._record_failure(model_id, e, target)
            return

        scan_task.cancel()

        # 用户在下载中取消？
        if model_id in self._cancels:
            self._cancels.discard(model_id)
            shutil.rmtree(target, ignore_errors=True)
            self._update_status(model_id, status="cancelled", progress=1.0, finished=True)
            await self._publish(
                "model_download_failed", model_id, extra={"cancelled": True}
            )
            return

        size_bytes = _dir_size_bytes(target) if target.exists() else 0
        self._update_status(
            model_id,
            status="ready",
            progress=1.0,
            size_bytes=size_bytes,
            finished=True,
        )
        await self._publish(
            "model_download_completed",
            model_id,
            extra={"size_bytes": size_bytes, "local_path": str(target)},
        )

    async def _watch_progress(
        self, model_id: int, target: Path, expected_bytes: int | None
    ) -> None:
        """后台每秒扫描目录 → 更新 DB progress + publish SSE。"""
        try:
            while True:
                await asyncio.sleep(_SCAN_INTERVAL)
                if not target.exists():
                    continue
                downloaded = _dir_size_bytes(target)
                if expected_bytes and expected_bytes > 0:
                    progress = min(0.99, downloaded / expected_bytes)
                else:
                    # custom 模型无预估总大小，保持最小可见进度
                    progress = 0.01
                self._update_progress_only(model_id, downloaded, progress)
                await self._publish(
                    "model_download_progress",
                    model_id,
                    extra={
                        "downloaded_bytes": downloaded,
                        "total_bytes": expected_bytes,
                    },
                )
        except asyncio.CancelledError:
            return

    # --- DB helpers ---------------------------------------------------

    def _load_model(self, model_id: int) -> Model:
        with Session(self._engine) as s:
            m = s.get(Model, model_id)
            if m is None:
                raise DownloadError(f"Model {model_id} not found")
            return m

    def _update_status(
        self,
        model_id: int,
        *,
        status: str,
        progress: float | None = None,
        local_path: str | None = None,
        size_bytes: int | None = None,
        started: bool = False,
        finished: bool = False,
    ) -> None:
        with Session(self._engine) as s:
            m = s.get(Model, model_id)
            if m is None:
                return
            m.status = status
            if progress is not None:
                m.progress = progress
            if local_path is not None:
                m.local_path = local_path
            if size_bytes is not None:
                m.size_bytes = size_bytes
            now = datetime.now(UTC)
            m.updated_at = now
            if started and not m.started_at:
                m.started_at = now
            if finished:
                m.finished_at = now
            s.add(m)
            s.commit()

    def _update_progress_only(
        self, model_id: int, downloaded_bytes: int, progress: float
    ) -> None:
        with Session(self._engine) as s:
            m = s.get(Model, model_id)
            if m is None or m.status != "downloading":
                return
            m.size_bytes = downloaded_bytes
            m.progress = progress
            m.updated_at = datetime.now(UTC)
            s.add(m)
            s.commit()

    def _record_failure(
        self, model_id: int, exc: Exception, target: Path
    ) -> None:
        code = exc.code if isinstance(exc, VoxCraftError) else "DOWNLOAD_FAILED"
        msg = exc.message if isinstance(exc, VoxCraftError) else str(exc)
        shutil.rmtree(target, ignore_errors=True)
        with Session(self._engine) as s:
            m = s.get(Model, model_id)
            if m is None:
                return
            m.status = "failed"
            m.error_code = code
            m.error_message = msg
            m.finished_at = datetime.now(UTC)
            m.updated_at = datetime.now(UTC)
            s.add(m)
            s.commit()
        asyncio.create_task(
            self._publish(
                "model_download_failed",
                model_id,
                extra={"error_code": code, "error_message": msg},
            )
        )

    # --- SSE ---------------------------------------------------------

    async def _publish(
        self,
        event_type: str,
        model_id: int,
        *,
        extra: dict[str, Any] | None = None,
    ) -> None:
        with Session(self._engine) as s:
            m = s.get(Model, model_id)
            if m is None:
                return
            payload: dict[str, Any] = {
                "model_id": model_id,
                "catalog_key": m.catalog_key,
                "status": m.status,
                "progress": m.progress,
            }
            if extra:
                payload.update(extra)
        await self._bus.publish(Event(type=event_type, payload=payload))


# --- utils -------------------------------------------------------------

def _dir_size_bytes(path: Path) -> int:
    if not path.exists():
        return 0
    if path.is_file():
        return path.stat().st_size
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


# Model 表的 started_at / finished_at 字段在阶段 1 未引入，
# 若未来需要再加 migration；当前兼容缺失字段：
_TIME_FIELDS = {"started_at", "finished_at"}
