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
    # 非克隆 Provider → preset，带 provider_name
    mock = next(v for v in voices if v["id"] == "mock-tts")
    assert mock["source"] == "preset"
    assert mock["provider_name"] == "mock-tts"


def test_tts_voices_excludes_cloning_providers_as_preset(client, mock_all_registered):
    """克隆型 Provider（CAPABILITIES 含 clone）不应作为 preset voice 列出。"""
    # 自建一个克隆 Provider（用 mock 实现，CAPABILITIES={'clone'}），
    # 验证不会被 /tts/voices 当 preset 罗列
    cloning = client.post("/api/admin/providers", json={
        "kind": "cloning",
        "name": "test-cloning",
        "class_name": "InMemoryMockCloningProvider",
        "config": {},
    }).json()

    r = client.get("/api/tts/voices")
    voices = r.json()["voices"]
    matches = [
        v for v in voices
        if v["id"] == cloning["name"] and v["source"] == "preset"
    ]
    assert matches == [], (
        f"cloning provider {cloning['name']} 不该出现 preset voice"
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

    r = client.get("/api/tts/voices")
    voices = r.json()["voices"]
    cloned = [v for v in voices if v["id"] == "vx_sample"]
    assert len(cloned) == 1
    assert cloned[0]["source"] == "cloned"
    assert cloned[0]["provider_name"] == "voxcpm-clone"


def test_tts_no_provider_returns_400(client):
    # 系统启动后无 Provider；提交 TTS 应返回 VALIDATION_ERROR
    r = client.post("/api/tts", json={"text": "hi", "voice_id": "x"})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"


def test_tts_accepts_cloning_provider_by_name(client, mock_all_registered):
    """/api/tts 显式指定 cloning kind 的 Provider 名时不应报"No tts provider"。

    回归 #issue：TtsDrawer 把 tts + cloning 合并显示，用户选 voxcpm-2（cloning kind）
    时路由曾硬限 kind=tts → "No tts provider available named voxcpm-2"。
    """
    p = client.post("/api/admin/providers", json={
        "kind": "cloning",
        "name": "mock-clone",
        "class_name": "InMemoryMockCloningProvider",
        "config": {},
    }).json()

    r = client.post(
        "/api/tts",
        json={"text": "hi", "voice_id": "anything", "provider": p["name"]},
    )
    # 路由放行（cloning Provider 也能合成）
    assert r.status_code == 202, r.text
