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
    voices = r.json()["voices"]
    ids = {v["id"] for v in voices}
    assert "mock-tts" in ids
    # 非克隆 Provider → preset，带 provider_name
    mock = next(v for v in voices if v["id"] == "mock-tts")
    assert mock["source"] == "preset"
    assert mock["provider_name"] == "mock-tts"


def test_tts_voices_excludes_cloning_providers_as_preset(client, mock_all_registered):
    """克隆型 Provider（CAPABILITIES 含 clone）不应作为 preset voice 列出。"""
    # seed 默认 voxcpm-clone（VoxCpmCloningProvider，CAPABILITIES={'clone'}）
    r = client.get("/tts/voices")
    voices = r.json()["voices"]
    # 没有 id 指向克隆 Provider 名的 preset
    seeded_cloning = client.get(
        "/admin/providers", params={"kind": "cloning"},
    ).json()
    for p in seeded_cloning:
        matches = [
            v for v in voices
            if v["id"] == p["name"] and v["source"] == "preset"
        ]
        assert matches == [], (
            f"cloning provider {p['name']} 不该出现 preset voice"
        )


def test_tts_voices_includes_voice_refs_as_cloned(client, mock_all_registered):
    """VoiceRef 条目（克隆生成的音色）应带 source=cloned + provider_name。"""
    from sqlmodel import Session
    from voxcraft.db.engine import get_engine
    from voxcraft.db.models import VoiceRef

    with Session(get_engine()) as s:
        s.add(VoiceRef(
            id="vx_sample", speaker_name="bob",
            reference_audio_path="/tmp/x.wav",
            provider_name="voxcpm-clone",
        ))
        s.commit()

    r = client.get("/tts/voices")
    voices = r.json()["voices"]
    cloned = [v for v in voices if v["id"] == "vx_sample"]
    assert len(cloned) == 1
    assert cloned[0]["source"] == "cloned"
    assert cloned[0]["provider_name"] == "voxcpm-clone"


def test_tts_no_provider_returns_400(client):
    # 禁用种子 tts provider
    seed = client.get("/admin/providers", params={"kind": "tts"}).json()[0]
    client.patch(f"/admin/providers/{seed['id']}", json={"enabled": False})

    r = client.post("/tts", json={"text": "hi", "voice_id": "x"})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"
