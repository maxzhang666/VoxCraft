"""Scheduler 接口与 IPC 数据类（ADR-013）。

- JobRequest / JobResult：主进程 ↔ worker 子进程传递的消息；必须 picklable
- Scheduler Protocol：两个后端（InProcess / Pool）的共同契约
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable


Kind = Literal["asr", "tts", "clone", "separate", "video_translate"]


@dataclass(frozen=True)
class JobRequest:
    """从主进程打包投递给 runner 的任务描述。

    输入输出均为标准类型，可跨进程 pickle。
    """

    job_id: str
    kind: Kind
    provider_name: str
    class_name: str
    provider_config: dict
    request_meta: dict
    source_path: str | None
    output_dir: str


@dataclass(frozen=True)
class JobResult:
    """runner 返回给主进程的结构化结果。

    成功：ok=True，按 kind 填 result / output_path / output_extras / voice_id
    失败：ok=False，填 error_code / error_message
    """

    ok: bool
    result: dict | None = None
    output_path: str | None = None
    output_extras: dict | None = None
    voice_id: str | None = None
    error_code: str | None = None
    error_message: str | None = None


@runtime_checkable
class Scheduler(Protocol):
    """Scheduler 后端的统一契约。"""

    @property
    def queue_size(self) -> int: ...

    async def submit(self, req: JobRequest) -> JobResult:
        """提交任务，等待终态返回。"""

    async def cancel(self, job_id: str) -> bool:
        """取消任务。

        - True：已真中断 / 已从队列移除，调用方可安全标 cancelled
        - False：未支持真取消（inprocess backend），或该 job 不在 scheduler 管辖
        """

    async def shutdown(self) -> None:
        """优雅停机。lifespan 结束时调用。"""
