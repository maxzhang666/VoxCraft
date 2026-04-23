"""/tts 和 /tts/voices 集成测试（异步模型）。"""
from __future__ import annotations

from tests.conftest import wait_for_job


def _create_and_set_default_mock_tts(client):
    p = client.post("/admin/providers", json={
        "kind": "tts",
        "name": "mock-tts",
        "class_name": "InMemoryMockTtsProvider",
        "config": {},
    }).json()
    client.post(f"/admin/providers/{p['id']}/set-default")
    return p


def test_tts_submits_and_produces_wav(client, mock_all_registered):
    _create_and_set_default_mock_tts(client)
    r = client.post("/tts", json={"text": "你好世界", "voice_id": "mock-voice"})
    assert r.status_code == 202, r.text
    job_id = r.json()["job_id"]
    assert r.json()["status"] == "pending"

    final = wait_for_job(client, job_id)
    assert final["status"] == "succeeded"
    assert final["provider_name"] == "mock-tts"

    out = client.get(f"/jobs/{job_id}/output")
    assert out.status_code == 200
    assert out.content.startswith(b"RIFF")


def test_tts_validates_empty_text(client, mock_all_registered):
    _create_and_set_default_mock_tts(client)
    r = client.post("/tts", json={"text": "", "voice_id": "x"})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"


def test_tts_voices_aggregates(client, mock_all_registered):
    _create_and_set_default_mock_tts(client)
    r = client.get("/tts/voices")
    assert r.status_code == 200
    ids = {v["id"] for v in r.json()["voices"]}
    assert "mock-tts" in ids


def test_tts_no_provider_returns_400(client):
    # 禁用种子 tts provider
    seed = client.get("/admin/providers", params={"kind": "tts"}).json()[0]
    client.patch(f"/admin/providers/{seed['id']}", json={"enabled": False})

    r = client.post("/tts", json={"text": "hi", "voice_id": "x"})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"
