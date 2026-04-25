"""/api/tts/voices/extract 端点测试。"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from voxcraft.api import voices as voices_module


def _create_cloning_provider(client: TestClient) -> dict:
    r = client.post("/api/admin/providers", json={
        "kind": "cloning",
        "name": "test-vox",
        "class_name": "VoxCpmCloningProvider",
        "config": {"model_dir": "/tmp/x", "device": "cpu"},
    })
    assert r.status_code == 201, r.text
    p = r.json()
    client.post(f"/api/admin/providers/{p['id']}/set-default")
    return p


@pytest.fixture(autouse=True)
def stub_extract_audio(tmp_path):
    """ffmpeg 不在测试环境运行，stub extract_audio 写入伪 WAV bytes。"""
    def _fake(src, dst, **_kw):
        Path(dst).parent.mkdir(parents=True, exist_ok=True)
        Path(dst).write_bytes(b"RIFF\x00\x00\x00\x00WAVEfmt mock")
    with patch.object(voices_module, "extract_audio", _fake), \
         patch.object(voices_module, "probe", return_value=type("P", (), {"duration": 5.0})()):
        yield


def test_extract_audio_creates_voice_ref(client):
    _create_cloning_provider(client)
    r = client.post(
        "/api/tts/voices/extract",
        files={"reference": ("ref.wav", b"RIFFfake", "audio/wav")},
        data={"speaker_name": "alice"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["voice_id"].startswith("vx_")
    assert body["speaker_name"] == "alice"
    assert body["provider_name"] == "test-vox"
    assert Path(body["reference_audio_path"]).exists()
    assert body["duration_seconds"] == 5.0


def test_extract_video_calls_ffmpeg(client):
    _create_cloning_provider(client)
    r = client.post(
        "/api/tts/voices/extract",
        files={"reference": ("clip.mp4", b"\x00\x00\x00\x18ftyp", "video/mp4")},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    # 输出路径 .wav 后缀（视频抽出来的音轨一律 WAV）
    assert body["reference_audio_path"].endswith(".wav")


def test_extract_unsupported_extension_rejected(client):
    _create_cloning_provider(client)
    r = client.post(
        "/api/tts/voices/extract",
        files={"reference": ("evil.exe", b"MZ\x00\x00", "application/octet-stream")},
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "INVALID_MEDIA"


def test_extract_without_cloning_provider_returns_400(client):
    # 没有 cloning Provider 时，_select_provider 抛 VALIDATION_ERROR
    r = client.post(
        "/api/tts/voices/extract",
        files={"reference": ("ref.wav", b"RIFFfake", "audio/wav")},
    )
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"


def test_delete_voice_removes_file_and_row(client):
    _create_cloning_provider(client)
    create = client.post(
        "/api/tts/voices/extract",
        files={"reference": ("ref.wav", b"RIFFfake", "audio/wav")},
    ).json()

    voice_id = create["voice_id"]
    ref_path = Path(create["reference_audio_path"])
    assert ref_path.exists()

    r = client.delete(f"/api/tts/voices/{voice_id}")
    assert r.status_code == 204
    assert not ref_path.exists()

    # voices 列表不再含
    voices = client.get("/api/tts/voices").json()["voices"]
    assert all(v["id"] != voice_id for v in voices)


def test_delete_unknown_voice_returns_404(client):
    r = client.delete("/api/tts/voices/vx_does-not-exist")
    assert r.status_code == 404


def test_delete_preset_voice_rejected(client):
    """preset 音色（id != vx_*）由 Provider 配置管理，不在此端点删除。"""
    # 先建 Piper Provider 让 /tts/voices 列出 preset
    client.post("/api/admin/providers", json={
        "kind": "tts",
        "name": "piper-zh",
        "class_name": "PiperProvider",
        "config": {"model": "/tmp/x.onnx"},
    })
    r = client.delete("/api/tts/voices/piper-zh")
    # preset id 不在 voice_refs 表 → 404 优先返回（实现细节）
    assert r.status_code == 404


def test_voice_sample_streams_reference_audio(client):
    """GET /api/tts/voices/{id}/sample 返回参考音频字节，供前端 <audio> 试听。"""
    _create_cloning_provider(client)
    create = client.post(
        "/api/tts/voices/extract",
        files={"reference": ("ref.wav", b"RIFFfake", "audio/wav")},
    ).json()
    voice_id = create["voice_id"]

    r = client.get(f"/api/tts/voices/{voice_id}/sample")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("audio/")
    assert len(r.content) > 0


def test_voice_sample_404_for_unknown(client):
    r = client.get("/api/tts/voices/vx_doesnotexist/sample")
    assert r.status_code == 404


def test_voice_sample_404_for_preset(client):
    r = client.get("/api/tts/voices/piper-zh/sample")
    assert r.status_code == 404


def test_list_voices_exposes_sample_url(client):
    _create_cloning_provider(client)
    create = client.post(
        "/api/tts/voices/extract",
        files={"reference": ("ref.wav", b"RIFFfake", "audio/wav")},
    ).json()
    voice_id = create["voice_id"]

    voices = client.get("/api/tts/voices").json()["voices"]
    cloned = next(v for v in voices if v["id"] == voice_id)
    assert cloned["sample_url"] == f"/api/tts/voices/{voice_id}/sample"
