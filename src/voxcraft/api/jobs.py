"""/jobs/* API。查询 + 详情 + 删除 + 重试 + 产物下载。"""
from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse
from sqlmodel import Session, select

from voxcraft.api.business import run_job
from voxcraft.api.schemas.job import JobResponse, JobSubmitResponse
from voxcraft.db.engine import get_engine
from voxcraft.db.models import Job
from voxcraft.errors import ValidationError, VoxCraftError
from voxcraft.events.bus import Event, EventBus


router = APIRouter(prefix="/jobs", tags=["jobs"])


def get_session():
    with Session(get_engine()) as s:
        yield s


def _not_found(id: str) -> VoxCraftError:
    return VoxCraftError(
        f"Job not found: {id}", code="JOB_NOT_FOUND", status_code=404
    )


@router.get("", response_model=list[JobResponse])
def list_jobs(
    kind: str | None = None,
    status: str | None = None,
    since: str | None = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_session),
):
    q = select(Job)
    if kind:
        q = q.where(Job.kind == kind)
    if status:
        q = q.where(Job.status == status)
    if since:
        try:
            dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
        except ValueError as e:
            raise ValidationError(f"Invalid `since`: {since}") from e
        q = q.where(Job.created_at >= dt)
    q = q.order_by(Job.created_at.desc()).offset(offset).limit(limit)
    return session.exec(q).all()


@router.get("/{id}", response_model=JobResponse)
def get_job(id: str, session: Session = Depends(get_session)):
    j = session.get(Job, id)
    if j is None:
        raise _not_found(id)
    return j


@router.delete("/{id}", status_code=204)
async def delete_job(
    id: str, request: Request, session: Session = Depends(get_session)
) -> None:
    j = session.get(Job, id)
    if j is None:
        raise _not_found(id)

    # 1. running 任务：请求 scheduler 真中断；成功则落 cancelled 审计
    #    - pool backend 会 SIGTERM worker 后 spawn；真释放 GPU
    #    - inprocess backend 无法中断同步 C 扩展，返回 False，后台自然跑完
    #      后在 _finalize_* 里检查到 cancelled 就跳过写回
    if j.status == "running":
        cancelled = await request.app.state.scheduler.cancel(j.id)
        if cancelled:
            bus = getattr(request.app.state, "event_bus", None)
            j.status = "cancelled"
            j.finished_at = datetime.utcnow()
            session.add(j)
            session.commit()
            if bus is not None:
                await bus.publish(
                    Event(
                        type="job_status_changed",
                        payload={"job_id": id, "kind": j.kind, "status": "cancelled"},
                    )
                )

    # 2. 清产物 + 原始上传
    paths: list[str] = []
    if j.source_path:
        paths.append(j.source_path)
    if j.output_path:
        paths.append(j.output_path)
    if j.output_extras:
        paths.extend(str(v) for v in j.output_extras.values())
    for p in paths:
        try:
            Path(p).unlink(missing_ok=True)
        except OSError:
            pass  # 忽略清理失败

    # 3. 删 DB 行
    session.delete(j)
    session.commit()


@router.post("/{id}/retry", response_model=JobSubmitResponse, status_code=202)
async def retry_job(
    id: str, request: Request, session: Session = Depends(get_session)
) -> JobSubmitResponse:
    """复用 job_id 重新入队。failed / cancelled / interrupted 可重试。

    interrupted: 进程崩溃 / 重启时残留的 running/pending Job（见 bootstrap），
    不会自动重跑（任务可能就是把进程拖崩的元凶），由用户在 UI 手动确认。
    """
    j = session.get(Job, id)
    if j is None:
        raise _not_found(id)
    if j.status not in {"failed", "cancelled", "interrupted"}:
        raise ValidationError(
            f"Cannot retry job in status: {j.status}",
            details={"job_id": id, "status": j.status},
        )
    # ASR/Clone/Separate 依赖原始音频；TTS 只需 request 里的文本
    if j.kind in {"asr", "clone", "separate"}:
        if not j.source_path or not Path(j.source_path).exists():
            raise VoxCraftError(
                "Source audio missing; cannot retry",
                code="SOURCE_MISSING",
                status_code=410,
            )
    # 清除上一轮的失败态 / 产物引用，重置为 pending
    j.status = "pending"
    j.progress = 0.0
    j.error_code = None
    j.error_message = None
    j.result = None
    j.output_path = None
    j.output_extras = None
    j.started_at = None
    j.finished_at = None
    session.add(j)
    session.commit()

    bus: EventBus | None = getattr(request.app.state, "event_bus", None)
    if bus is not None:
        await bus.publish(
            Event(
                type="job_status_changed",
                payload={"job_id": id, "kind": j.kind, "status": "pending"},
            )
        )
    asyncio.create_task(run_job(id, request.app.state))
    return JobSubmitResponse(job_id=id, status="pending")


def _resolve_output(j: Job, key: str | None) -> Path:
    if key:
        path_str = (j.output_extras or {}).get(key)
    else:
        path_str = j.output_path
    if not path_str:
        raise VoxCraftError(
            "Job output not ready",
            code="JOB_OUTPUT_NOT_READY",
            status_code=404,
        )
    path = Path(path_str)
    if not path.exists():
        raise VoxCraftError(
            "Job output missing on disk",
            code="JOB_OUTPUT_MISSING",
            status_code=410,
        )
    return path


@router.get("/{id}/output")
def download_output(
    id: str,
    key: str | None = None,
    session: Session = Depends(get_session),
):
    j = session.get(Job, id)
    if j is None:
        raise _not_found(id)
    path = _resolve_output(j, key)
    return FileResponse(
        path, filename=path.name, media_type="application/octet-stream"
    )


@router.get("/{id}/output/preview")
def preview_output(
    id: str,
    key: str | None = None,
    session: Session = Depends(get_session),
):
    j = session.get(Job, id)
    if j is None:
        raise _not_found(id)
    path = _resolve_output(j, key)
    return FileResponse(path)  # 无 Content-Disposition，浏览器内联
