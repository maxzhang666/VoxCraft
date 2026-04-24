"""/asr 端点集成测试（异步模型，Mock ASR Provider）。"""
from __future__ import annotations

from tests.conftest import wait_for_job


def _create_mock_asr(client):
    r = client.post("/api/admin/providers", json={
        "kind": "asr",
        "name": "mock-asr",
        "class_name": "InMemoryMockAsrProvider",
        "config": {},
    })
    assert r.status_code == 201
    pid = r.json()["id"]
    # 设为默认（覆盖种子的 whisper-medium-int8）
    client.post(f"/api/admin/providers/{pid}/set-default")


def test_asr_returns_segments(client, mock_asr_registered):
    _create_mock_asr(client)
    r = client.post(
        "/api/asr",
        files={"audio": ("sample.wav", b"RIFFfakewave", "audio/wav")},
    )
    assert r.status_code == 202, r.text
    job_id = r.json()["job_id"]
    final = wait_for_job(client, job_id)
    assert final["status"] == "succeeded"
    assert final["provider_name"] == "mock-asr"
    result = final["result"]
    assert result["language"]
    assert len(result["segments"]) >= 1
    assert "text" in result["segments"][0]


def test_asr_uses_language_param(client, mock_asr_registered):
    _create_mock_asr(client)
    r = client.post(
        "/api/asr",
        files={"audio": ("a.wav", b"RIFF", "audio/wav")},
        data={"language": "en"},
    )
    assert r.status_code == 202
    job_id = r.json()["job_id"]
    final = wait_for_job(client, job_id)
    assert final["status"] == "succeeded"
    assert final["result"]["language"] == "en"


def test_asr_no_provider_returns_validation_error(client, mock_asr_registered):
    # 禁用种子 ASR Provider
    seed = client.get("/api/admin/providers", params={"kind": "asr"}).json()[0]
    client.patch(f"/api/admin/providers/{seed['id']}", json={"enabled": False})

    r = client.post(
        "/api/asr",
        files={"audio": ("a.wav", b"RIFF", "audio/wav")},
    )
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"


def test_asr_explicit_provider_name(client, mock_asr_registered):
    _create_mock_asr(client)
    r = client.post(
        "/api/asr",
        files={"audio": ("a.wav", b"RIFF", "audio/wav")},
        data={"provider": "mock-asr"},
    )
    assert r.status_code == 202
    job_id = r.json()["job_id"]
    final = wait_for_job(client, job_id)
    assert final["status"] == "succeeded"
    assert final["provider_name"] == "mock-asr"


def test_asr_emits_job_progress_events(client, mock_asr_registered):
    """Mock ASR 内置 progress_cb(0.5) + (1.0) 调用；事件应到 EventBus → SSE 订阅方。"""
    _create_mock_asr(client)

    # 直接在主进程订阅 EventBus（测试层，不走 HTTP SSE）
    from fastapi import FastAPI
    app: FastAPI = client.app  # type: ignore[attr-defined]
    bus = app.state.event_bus
    q = bus.subscribe()

    r = client.post(
        "/api/asr",
        files={"audio": ("a.wav", b"RIFFfake", "audio/wav")},
        data={"language": "zh"},
    )
    assert r.status_code == 202
    job_id = r.json()["job_id"]
    final = wait_for_job(client, job_id)
    assert final["status"] == "succeeded"

    # 读出所有事件，找 job_progress
    events: list[dict] = []
    while not q.empty():
        events.append(q.get_nowait().__dict__)
    bus.unsubscribe(q)

    progresses = [
        e for e in events
        if e["type"] == "job_progress" and e["payload"].get("job_id") == job_id
    ]
    assert len(progresses) >= 2, f"expected >=2 progress events, got {len(progresses)}"
    values = [p["payload"]["progress"] for p in progresses]
    assert 0.5 in values or any(abs(v - 0.5) < 1e-6 for v in values)
    assert 1.0 in values or any(abs(v - 1.0) < 1e-6 for v in values)
