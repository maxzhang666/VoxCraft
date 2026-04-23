"""/asr 端点集成测试（异步模型，Mock ASR Provider）。"""
from __future__ import annotations

from tests.conftest import wait_for_job


def _create_mock_asr(client):
    r = client.post("/admin/providers", json={
        "kind": "asr",
        "name": "mock-asr",
        "class_name": "InMemoryMockAsrProvider",
        "config": {},
    })
    assert r.status_code == 201
    pid = r.json()["id"]
    # 设为默认（覆盖种子的 whisper-medium-int8）
    client.post(f"/admin/providers/{pid}/set-default")


def test_asr_returns_segments(client, mock_asr_registered):
    _create_mock_asr(client)
    r = client.post(
        "/asr",
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
        "/asr",
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
    seed = client.get("/admin/providers", params={"kind": "asr"}).json()[0]
    client.patch(f"/admin/providers/{seed['id']}", json={"enabled": False})

    r = client.post(
        "/asr",
        files={"audio": ("a.wav", b"RIFF", "audio/wav")},
    )
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"


def test_asr_explicit_provider_name(client, mock_asr_registered):
    _create_mock_asr(client)
    r = client.post(
        "/asr",
        files={"audio": ("a.wav", b"RIFF", "audio/wav")},
        data={"provider": "mock-asr"},
    )
    assert r.status_code == 202
    job_id = r.json()["job_id"]
    final = wait_for_job(client, job_id)
    assert final["status"] == "succeeded"
    assert final["provider_name"] == "mock-asr"
