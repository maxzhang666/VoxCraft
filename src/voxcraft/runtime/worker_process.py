"""Worker 子进程入口（ADR-013）。

主循环极简：阻塞从 submit_queue 取 JobRequest → run_sync → 结果进 result_queue。
- LRU=1 在本进程内维护；跨 job 复用已加载的 Provider
- 未捕获异常封装成 JobResult(ok=False, error_code=WORKER_ERROR)；worker 不崩溃
- 收到 None sentinel → 优雅退出
- `extra_class_imports`：允许测试注入 Mock Provider（生产路径为空）

**不** 依赖 asyncio；worker 是同步单线程。
"""
from __future__ import annotations

import importlib
import logging
import os
import signal
from multiprocessing.queues import Queue

from voxcraft.providers.registry import PROVIDER_REGISTRY
from voxcraft.runtime.scheduler_api import JobRequest, JobResult
from voxcraft.runtime.worker_runners import _LruOne, run as run_sync


_log = logging.getLogger("voxcraft.worker")


def _install_extra_classes(extra: list[str]) -> None:
    """按 `module.path:ClassName` 注入额外 Provider 类到本进程 registry。"""
    for spec in extra:
        if ":" not in spec:
            _log.warning("worker.extra_class.bad_spec", extra={"spec": spec})
            continue
        module_path, cls_name = spec.split(":", 1)
        try:
            mod = importlib.import_module(module_path)
            cls = getattr(mod, cls_name)
            PROVIDER_REGISTRY[cls_name] = cls
        except Exception as e:  # noqa: BLE001
            _log.warning("worker.extra_class.failed", extra={"spec": spec, "err": str(e)})


def worker_main(
    submit_q: "Queue[JobRequest | None]",
    result_q: "Queue[tuple[str, JobResult]]",
    extra_class_imports: list[str],
) -> None:
    """子进程入口。跑到 None sentinel / SIGTERM 时退出。"""
    # SIGTERM 默认处理：解释器直接退出，未完成 job 的 future 由主进程的
    # cancel 路径设为 cancelled。不安装自定义 handler（防止和信号传递冲突）。
    signal.signal(signal.SIGTERM, signal.SIG_DFL)

    _install_extra_classes(extra_class_imports)
    lru = _LruOne()
    _log.info("worker.started", extra={"pid": os.getpid()})

    while True:
        req = submit_q.get()
        if req is None:
            _log.info("worker.shutdown")
            return
        try:
            res = run_sync(req, lru)
        except BaseException as e:  # noqa: BLE001
            # run_sync 已做 VoxCraftError 转换；这里兜底最后一层
            res = JobResult(
                ok=False,
                error_code="WORKER_ERROR",
                error_message=f"{type(e).__name__}: {e}",
            )
        result_q.put((req.job_id, res))
