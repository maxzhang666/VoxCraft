"""Pool Scheduler：单 worker 子进程 + 真取消（ADR-013）。

架构：
- 一个常驻 worker 子进程（spawn 上下文，避免 fork + CUDA 问题）
- 主进程 ↔ worker 通过两个 mp.Queue：submit（下行 JobRequest）/ result（上行 (job_id, JobResult)）
- 主进程维护 `_futures: Dict[str, asyncio.Future[JobResult]]`
- 一个 `result_consumer` 协程不停从 result_queue 读 → 用 loop.call_soon_threadsafe 设 Future 结果
- submit_queue 用 `asyncio.to_thread(put)` 投递，避免阻塞事件循环
- cancel(job_id): 若等于当前 running → SIGTERM worker + respawn + 将 Future 设为 cancelled
  否则返回 False（pending job 的 cancel 暂不支持，第一版接受此限制）

并发模型：
- worker 进程内严格单线程（串行）；主进程 scheduler 持有 asyncio.Lock 保证同一时刻只有一个
  outstanding submit —— 维持 ADR-008 全局单任务语义
"""
from __future__ import annotations

import asyncio
import logging
import multiprocessing as mp
from multiprocessing.context import SpawnContext, SpawnProcess
from multiprocessing.queues import Queue

from voxcraft.events.bus import Event, EventBus
from voxcraft.runtime.scheduler_api import JobRequest, JobResult
from voxcraft.runtime.worker_process import worker_main


_log = logging.getLogger("voxcraft.pool")


class PoolScheduler:
    def __init__(
        self,
        bus: EventBus | None = None,
        extra_class_imports: list[str] | None = None,
        start_method: str = "spawn",
    ) -> None:
        """
        start_method:
          - "spawn"（默认，生产）：CUDA 安全；子进程完全独立
          - "forkserver"（测试推荐）：绕过 spawn 在 pytest 下 re-import sys.argv[0] 的坑
          - "fork"：不推荐（CUDA 下易死锁）
        """
        self._bus = bus
        self._extra = list(extra_class_imports or [])
        self._ctx: SpawnContext = mp.get_context(start_method)  # type: ignore[assignment]
        self._submit_q: Queue = self._ctx.Queue()
        self._result_q: Queue = self._ctx.Queue()
        self._worker: SpawnProcess | None = None
        self._lock = asyncio.Lock()  # 维持全局单任务语义
        self._active = 0

        # 跟踪中的任务（job_id → Future）
        self._futures: dict[str, asyncio.Future[JobResult]] = {}
        self._current_job_id: str | None = None

        self._consumer_task: asyncio.Task | None = None
        self._started = False

    # ---------- 生命周期 ----------

    async def start(self) -> None:
        if self._started:
            return
        self._spawn_worker()
        loop = asyncio.get_running_loop()
        self._consumer_task = loop.create_task(self._result_consumer())
        self._started = True

    def _spawn_worker(self) -> None:
        p: SpawnProcess = self._ctx.Process(
            target=worker_main,
            args=(self._submit_q, self._result_q, self._extra),
            name="voxcraft-worker",
            daemon=True,
        )
        p.start()
        self._worker = p
        _log.info("pool.worker.spawned", extra={"pid": p.pid})

    async def shutdown(self) -> None:
        if not self._started:
            return
        self._started = False  # 先标记防止 submit 再进来

        # 1. 给 worker 发 None sentinel 让其自然退出
        try:
            await asyncio.to_thread(self._submit_q.put, None)
        except BaseException:  # noqa: BLE001
            pass

        # 2. 等 worker 退出（超时则强杀）
        if self._worker is not None:
            try:
                await asyncio.to_thread(self._worker.join, 3.0)
            finally:
                if self._worker.is_alive():
                    self._worker.terminate()
                    await asyncio.to_thread(self._worker.join, 2.0)

        # 3. 给 result_consumer 送一个毒丸，让 blocking get() 返回
        #    consumer 识别 sentinel (None,None) 后 return，事件循环可清理
        try:
            self._result_q.put_nowait((None, None))  # type: ignore[arg-type]
        except BaseException:  # noqa: BLE001
            pass
        if self._consumer_task is not None:
            try:
                await asyncio.wait_for(self._consumer_task, timeout=2.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                self._consumer_task.cancel()

    # ---------- 核心：submit / cancel ----------

    @property
    def queue_size(self) -> int:
        return max(0, self._active - 1)

    async def _publish_size(self) -> None:
        if self._bus is None:
            return
        await self._bus.publish(
            Event(type="queue_size_changed", payload={"size": self.queue_size})
        )

    async def submit(self, req: JobRequest) -> JobResult:
        if not self._started:
            await self.start()

        loop = asyncio.get_running_loop()
        future: asyncio.Future[JobResult] = loop.create_future()
        self._futures[req.job_id] = future

        self._active += 1
        await self._publish_size()
        try:
            async with self._lock:
                # 串行投递；下一 submit 需等这个 Future done
                self._current_job_id = req.job_id
                await asyncio.to_thread(self._submit_q.put, req)
                return await future
        finally:
            self._current_job_id = None
            self._futures.pop(req.job_id, None)
            self._active -= 1
            await self._publish_size()

    async def cancel(self, job_id: str) -> bool:
        """仅当 job_id 正在 worker 中运行时真取消（SIGTERM + respawn）。"""
        if job_id != self._current_job_id:
            return False

        # 1. kill worker
        w = self._worker
        if w is not None and w.is_alive():
            w.terminate()
            await asyncio.to_thread(w.join, 2.0)
            if w.is_alive():
                w.kill()
                await asyncio.to_thread(w.join, 1.0)

        # 2. 把等待的 future 设为 cancelled 结果
        future = self._futures.get(job_id)
        if future is not None and not future.done():
            future.set_result(
                JobResult(
                    ok=False,
                    error_code="CANCELLED",
                    error_message="Job cancelled by user",
                )
            )

        # 3. spawn 新 worker 接管后续任务（LRU=1 冷启动，是真取消的代价）
        self._spawn_worker()
        return True

    # ---------- result consumer ----------

    async def _result_consumer(self) -> None:
        loop = asyncio.get_running_loop()
        while True:
            try:
                job_id, result = await asyncio.to_thread(self._result_q.get)
            except asyncio.CancelledError:
                return
            except BaseException as e:  # noqa: BLE001
                _log.error("pool.consumer.error", extra={"err": str(e)})
                await asyncio.sleep(0.1)
                continue
            # shutdown 毒丸
            if job_id is None and result is None:
                return
            future = self._futures.get(job_id)
            if future is not None and not future.done():
                # 跨线程设置 future（get 在线程池中拿到结果后回到主 loop）
                loop.call_soon_threadsafe(future.set_result, result)
