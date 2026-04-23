"""OpenAI 兼容 API 层集成测试（ADR-012）。

覆盖：
- /v1/audio/transcriptions 五种 response_format（json/text/srt/vtt/verbose_json）
- /v1/audio/speech 基本流程 + 响应头追溯
- error envelope 形状
- model 字段的 provider 映射
"""
from __future__ import annotations


def _seed_mock_asr(client):
    p = client.post("/admin/providers", json={
        "kind": "asr", "name": "mock-asr",
        "class_name": "InMemoryMockAsrProvider", "config": {},
    }).json()
    client.post(f"/admin/providers/{p['id']}/set-default")
    return p


def _seed_mock_tts(client):
    p = client.post("/admin/providers", json={
        "kind": "tts", "name": "mock-tts",
        "class_name": "InMemoryMockTtsProvider", "config": {},
    }).json()
    client.post(f"/admin/providers/{p['id']}/set-default")
    return p


# ---------- Transcriptions ----------

def test_transcriptions_json(client, mock_all_registered):
    _seed_mock_asr(client)
    r = client.post(
        "/v1/audio/transcriptions",
        files={"file": ("a.wav", b"RIFFfake", "audio/wav")},
        data={"model": "whisper-1", "response_format": "json"},
    )
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("application/json")
    assert "X-VoxCraft-Job-Id" in r.headers
    body = r.json()
    assert "text" in body
    assert isinstance(body["text"], str)


def test_transcriptions_text(client, mock_all_registered):
    _seed_mock_asr(client)
    r = client.post(
        "/v1/audio/transcriptions",
        files={"file": ("a.wav", b"RIFFfake", "audio/wav")},
        data={"model": "whisper-1", "response_format": "text"},
    )
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/plain")
    assert r.text  # 非空


def test_transcriptions_verbose_json(client, mock_all_registered):
    _seed_mock_asr(client)
    r = client.post(
        "/v1/audio/transcriptions",
        files={"file": ("a.wav", b"RIFFfake", "audio/wav")},
        data={"model": "whisper-1", "response_format": "verbose_json", "language": "zh"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["task"] == "transcribe"
    assert body["language"]
    assert isinstance(body["duration"], (int, float))
    assert isinstance(body["segments"], list)
    assert len(body["segments"]) >= 1
    seg0 = body["segments"][0]
    assert {"id", "start", "end", "text"} <= set(seg0.keys())


def test_transcriptions_srt(client, mock_all_registered):
    _seed_mock_asr(client)
    r = client.post(
        "/v1/audio/transcriptions",
        files={"file": ("a.wav", b"RIFFfake", "audio/wav")},
        data={"model": "whisper-1", "response_format": "srt"},
    )
    assert r.status_code == 200
    # SRT 结构：index + 时间戳行 + 文本 + 空行
    assert "-->" in r.text
    assert r.text.startswith("1\n")


def test_transcriptions_vtt(client, mock_all_registered):
    _seed_mock_asr(client)
    r = client.post(
        "/v1/audio/transcriptions",
        files={"file": ("a.wav", b"RIFFfake", "audio/wav")},
        data={"model": "whisper-1", "response_format": "vtt"},
    )
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/vtt")
    assert r.text.startswith("WEBVTT")


def test_transcriptions_default_format_is_json(client, mock_all_registered):
    _seed_mock_asr(client)
    r = client.post(
        "/v1/audio/transcriptions",
        files={"file": ("a.wav", b"RIFFfake", "audio/wav")},
    )
    assert r.status_code == 200
    assert "text" in r.json()


def test_transcriptions_no_provider_returns_oai_error_envelope(client, mock_all_registered):
    # 禁用种子；Mock 未注入默认 → select_provider 抛 VALIDATION_ERROR
    for p in client.get("/admin/providers", params={"kind": "asr"}).json():
        client.patch(f"/admin/providers/{p['id']}", json={"enabled": False})

    r = client.post(
        "/v1/audio/transcriptions",
        files={"file": ("a.wav", b"RIFFfake", "audio/wav")},
    )
    assert r.status_code == 400
    body = r.json()
    assert "error" in body
    assert body["error"]["type"] == "invalid_request_error"
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert body["error"]["message"]


def test_transcriptions_explicit_provider_via_model_field(client, mock_all_registered):
    """传具体 provider name 应被 `_resolve_provider_name` 解析。"""
    _seed_mock_asr(client)
    r = client.post(
        "/v1/audio/transcriptions",
        files={"file": ("a.wav", b"RIFFfake", "audio/wav")},
        data={"model": "mock-asr"},
    )
    assert r.status_code == 200
    # 验证用的确是 mock-asr（通过 X-VoxCraft-Job-Id 拉详情）
    job_id = r.headers["X-VoxCraft-Job-Id"]
    job = client.get(f"/jobs/{job_id}").json()
    assert job["provider_name"] == "mock-asr"


# ---------- Speech ----------

def test_speech_wav(client, mock_all_registered):
    _seed_mock_tts(client)
    r = client.post(
        "/v1/audio/speech",
        json={
            "model": "tts-1",
            "input": "你好世界",
            "voice": "alloy",
            "response_format": "wav",
        },
    )
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "audio/wav"
    assert "X-VoxCraft-Job-Id" in r.headers
    assert r.content.startswith(b"RIFF")


def test_speech_mp3_format_header(client, mock_all_registered):
    """即便底层 Mock 只出 wav，Content-Type 按请求的 format 上报（OpenAI 契约）。"""
    _seed_mock_tts(client)
    r = client.post(
        "/v1/audio/speech",
        json={"model": "tts-1", "input": "hi", "voice": "alloy", "response_format": "mp3"},
    )
    assert r.status_code == 200
    assert r.headers["content-type"] == "audio/mpeg"


def test_speech_validation_error_for_empty_input(client, mock_all_registered):
    _seed_mock_tts(client)
    r = client.post(
        "/v1/audio/speech",
        json={"model": "tts-1", "input": "", "voice": "alloy"},
    )
    assert r.status_code == 400
    body = r.json()
    assert body["error"]["type"] == "invalid_request_error"
    assert body["error"]["code"] == "VALIDATION_ERROR"


def test_speech_no_provider_returns_oai_error(client):
    for p in client.get("/admin/providers", params={"kind": "tts"}).json():
        client.patch(f"/admin/providers/{p['id']}", json={"enabled": False})

    r = client.post(
        "/v1/audio/speech",
        json={"model": "tts-1", "input": "hi", "voice": "alloy"},
    )
    assert r.status_code == 400
    body = r.json()
    assert body["error"]["type"] == "invalid_request_error"
    assert body["error"]["code"] == "VALIDATION_ERROR"
