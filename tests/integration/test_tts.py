"""/tts 和 /tts/voices 集成测试（异步模型）。"""
from __future__ import annotations

from tests.conftest import wait_for_job


def _create_and_set_default_mock_tts(client):
    p = client.post("/api/admin/providers", json={
        "kind": "tts",
        "name": "mock-tts",
        "class_name": "InMemoryMockTtsProvider",
        "config": {},
    }).json()
    client.post(f"/api/admin/providers/{p['id']}/set-default")
    return p


def test_tts_submits_and_produces_wav(client, mock_all_registered):
    _create_and_set_default_mock_tts(client)
    r = client.post("/api/tts", json={"text": "你好世界", "voice_id": "mock-voice"})
    assert r.status_code == 202, r.text
    job_id = r.json()["job_id"]
    assert r.json()["status"] == "pending"

    final = wait_for_job(client, job_id)
    assert final["status"] == "succeeded"
    assert final["provider_name"] == "mock-tts"

    out = client.get(f"/api/jobs/{job_id}/output")
    assert out.status_code == 200
    assert out.content.startswith(b"RIFF")


def test_tts_validates_empty_text(client, mock_all_registered):
    _create_and_set_default_mock_tts(client)
    r = client.post("/api/tts", json={"text": "", "voice_id": "x"})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"


def test_tts_voices_aggregates(client, mock_all_registered):
    _create_and_set_default_mock_tts(client)
    r = client.get("/api/tts/voices")
    assert r.status_code == 200
    voices = r.json()["voices"]
    ids = {v["id"] for v in voices}
    assert "mock-tts" in ids
    # 预设 Provider → preset，带 provider_name
    mock = next(v for v in voices if v["id"] == "mock-tts")
    assert mock["source"] == "preset"
    assert mock["provider_name"] == "mock-tts"


def test_tts_no_provider_returns_400(client):
    # 系统启动后无 Provider；提交 TTS 应返回 VALIDATION_ERROR
    r = client.post("/api/tts", json={"text": "hi", "voice_id": "x"})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"
