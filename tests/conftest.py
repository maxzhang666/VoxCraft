"""测试共享 fixture。

- `client`：function-scope TestClient（每测试一套独立 DB + 产物目录）
- `mock_asr_registered`：把 InMemoryMockAsrProvider 注入 registry
- `wait_for_job`：业务端点现为异步，helper 轮询 Job 至终态
"""
from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from voxcraft.config import get_settings
from voxcraft.db.engine import get_engine
from voxcraft.providers import registry
from voxcraft.providers.mock import InMemoryMockAsrProvider


def wait_for_job(
    client: TestClient, job_id: str, *, timeout: float = 5.0, interval: float = 0.02
) -> dict:
    """轮询 /jobs/{id} 直到终态（succeeded/failed/cancelled）。返回最终 Job 字典。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = client.get(f"/jobs/{job_id}")
        assert r.status_code == 200, r.text
        j = r.json()
        if j["status"] in ("succeeded", "failed", "cancelled"):
            return j
        time.sleep(interval)
    raise AssertionError(f"Job {job_id} did not terminate within {timeout}s")


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("VOXCRAFT_DB", str(tmp_path / "voxcraft.sqlite"))
    monkeypatch.setenv("VOXCRAFT_OUTPUT_DIR", str(tmp_path / "outputs"))
    monkeypatch.setenv("VOXCRAFT_MODELS_DIR", str(tmp_path / "models"))
    get_settings.cache_clear()
    get_engine.cache_clear()

    from voxcraft.main import create_app
    app = create_app()
    with TestClient(app) as c:
        yield c

    get_settings.cache_clear()
    get_engine.cache_clear()


@pytest.fixture
def mock_asr_registered(monkeypatch):
    monkeypatch.setitem(
        registry.PROVIDER_REGISTRY,
        "InMemoryMockAsrProvider",
        InMemoryMockAsrProvider,
    )


@pytest.fixture
def mock_all_registered(monkeypatch):
    """一次性注入全部 Mock Provider 供 TTS/Clone/Separate 集成测试。"""
    from voxcraft.providers.mock import (
        InMemoryMockCloningProvider,
        InMemoryMockSeparatorProvider,
        InMemoryMockTtsProvider,
    )
    for cls in (
        InMemoryMockAsrProvider,
        InMemoryMockTtsProvider,
        InMemoryMockCloningProvider,
        InMemoryMockSeparatorProvider,
    ):
        monkeypatch.setitem(registry.PROVIDER_REGISTRY, cls.__name__, cls)
