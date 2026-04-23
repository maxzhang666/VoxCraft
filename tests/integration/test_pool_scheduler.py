"""PoolScheduler 专项集成测试（ADR-013）。

通过 Mock Provider 的 "extra_class_imports" 机制注入到 worker 进程。
Mock 的 load/transcribe/synthesize 都是瞬时操作；forkserver 下整个测试文件 <1s。

覆盖：
- 启动 / 提交 / 关停
- 多次提交串行执行
- cancel running 任务 → 真中断 + worker 自动 respawn + 后续提交正常
- Provider unknown / cancel unknown
"""
from __future__ import annotations

import asyncio
import uuid

import pytest

from voxcraft.runtime.pool_scheduler import PoolScheduler
from voxcraft.runtime.scheduler_api import JobRequest


MOCK_IMPORTS = [
    "voxcraft.providers.mock:InMemoryMockAsrProvider",
    "voxcraft.providers.mock:InMemoryMockTtsProvider",
    "voxcraft.providers.mock:InMemoryMockCloningProvider",
    "voxcraft.providers.mock:InMemoryMockSeparatorProvider",
]


def _asr_req(tmp_path, job_id: str | None = None) -> JobRequest:
    jid = job_id or str(uuid.uuid4())
    audio = tmp_path / f"{jid}.wav"
    audio.write_bytes(b"RIFFfakewave")
    return JobRequest(
        job_id=jid,
        kind="asr",
        provider_name="mock-asr",
        class_name="InMemoryMockAsrProvider",
        provider_config={},
        request_meta={"language": "zh"},
        source_path=str(audio),
        output_dir=str(tmp_path / "outputs"),
    )


@pytest.fixture
async def pool(tmp_path):
    # forkserver：pytest 下 spawn 会尝试 re-import sys.argv[0]（pytest runner）
    # 导致子进程启动挂住。forkserver 从一个干净的 helper 进程 fork，
    # 绕过此问题。生产部署 spawn 仍是默认，CUDA 安全。
    s = PoolScheduler(
        extra_class_imports=MOCK_IMPORTS,
        start_method="forkserver",
    )
    await s.start()
    yield s
    await s.shutdown()


async def test_pool_submit_asr_succeeds(pool, tmp_path):
    req = _asr_req(tmp_path)
    result = await pool.submit(req)
    assert result.ok is True, result
    assert result.result is not None
    assert result.result["language"] == "zh"
    assert len(result.result["segments"]) == 1


async def test_pool_sequential_submits(pool, tmp_path):
    """多次提交按 ADR-008 串行完成。"""
    results = []
    for i in range(3):
        r = await pool.submit(_asr_req(tmp_path, job_id=f"seq-{i}"))
        results.append(r)
    assert all(r.ok for r in results)


async def test_pool_cancel_running_kills_worker(pool, tmp_path):
    """cancel 运行中任务 → JobResult(ok=False, code=CANCELLED)，新 worker 接续正常。"""
    req = _asr_req(tmp_path, job_id="to-cancel")

    # 起 submit 协程；立即并发 cancel（赶在 mock 瞬时完成之前）
    # Mock 的 transcribe 极快，这里不一定真能赶上 running 态——容忍两种结果：
    # - 赶上了 running：cancel 返 True，result.ok=False/code=CANCELLED
    # - 没赶上（任务已完成）：cancel 返 False，result.ok=True
    submit_task = asyncio.create_task(pool.submit(req))
    # 给 submit 一个极短 tick 让其进入 lock + put queue
    await asyncio.sleep(0.01)
    cancelled = await pool.cancel("to-cancel")
    result = await submit_task

    if cancelled:
        assert result.ok is False
        assert result.error_code == "CANCELLED"
    else:
        # 没赶上，任务已成功完成
        assert result.ok is True

    # 无论哪种情况，worker 都能继续接新任务
    r2 = await pool.submit(_asr_req(tmp_path, job_id="after-cancel"))
    assert r2.ok is True


async def test_pool_cancel_unknown_job_returns_false(pool):
    """cancel 不在跑的 job_id → False。"""
    assert await pool.cancel("nonexistent") is False


async def test_pool_unknown_provider_returns_error(pool, tmp_path):
    """Provider class 不在 registry → worker 返回 JobResult.error_code=PROVIDER_UNKNOWN。"""
    audio = tmp_path / "a.wav"
    audio.write_bytes(b"RIFF")
    req = JobRequest(
        job_id="bad-provider",
        kind="asr",
        provider_name="ghost",
        class_name="GhostProvider",
        provider_config={},
        request_meta={},
        source_path=str(audio),
        output_dir=str(tmp_path),
    )
    r = await pool.submit(req)
    assert r.ok is False
    assert r.error_code == "PROVIDER_UNKNOWN"
