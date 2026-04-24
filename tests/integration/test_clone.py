"""/tts/clone 集成测试（异步模型）。"""
from __future__ import annotations

from tests.conftest import wait_for_job


def _create_and_set_default_mock_cloning(client):
    p = client.post("/api/admin/providers", json={
        "kind": "cloning",
        "name": "mock-clone",
        "class_name": "InMemoryMockCloningProvider",
        "config": {},
    }).json()
    client.post(f"/api/admin/providers/{p['id']}/set-default")
    return p


def test_clone_returns_audio_and_voice_id(client, mock_all_registered):
    _create_and_set_default_mock_cloning(client)
    r = client.post(
        "/api/tts/clone",
        files={"reference_audio": ("ref.wav", b"RIFFref", "audio/wav")},
        data={"text": "测试克隆", "speaker_name": "张三"},
    )
    assert r.status_code == 202, r.text
    job_id = r.json()["job_id"]
    final = wait_for_job(client, job_id)
    assert final["status"] == "succeeded"
    voice_id = final["request"]["voice_id"]
    assert voice_id.startswith("vx_mock_")

    # 产物可下载
    out = client.get(f"/api/jobs/{job_id}/output")
    assert out.status_code == 200
    assert out.content.startswith(b"RIFF")

    # 声纹进 voice_refs 表 → /tts/voices 聚合里可查到
    voices = client.get("/api/tts/voices").json()["voices"]
    assert any(v["id"] == voice_id for v in voices)
