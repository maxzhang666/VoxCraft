"""/video-translate 提交 + 前置验证（ADR-014 / v0.4.0 阶段 2）。

本测试覆盖 HTTP 入口层：
- 14 条前置验证规则各至少一个失败用例
- 合法请求写 Job(kind=video_translate, status=pending) 并返回 202
- 音频输入 vs 视频输入的差异（subtitle_mode 对音频失效）

运行态（真正的 ASR→LLM→TTS→mux）属阶段 3 E2E 范围，这里不覆盖。
"""
from __future__ import annotations

import io

from sqlmodel import Session

from voxcraft.db.engine import get_engine
from voxcraft.db.models import Job, LlmProvider, Provider


# ---------- helpers ----------

def _seed_llm(client, **overrides) -> dict:
    body = {
        "name": "openai",
        "base_url": "https://api.openai.com/v1",
        "api_key": "sk-test",
        "model": "gpt-4o-mini",
        **overrides,
    }
    r = client.post("/api/admin/llm", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _get_provider_id(kind: str, class_name: str | None = None) -> int:
    from sqlmodel import select
    with Session(get_engine()) as s:
        q = select(Provider).where(Provider.kind == kind)
        if class_name:
            q = q.where(Provider.class_name == class_name)
        row = s.exec(q).first()
        assert row is not None
        return row.id  # type: ignore[return-value]


def _fake_audio_bytes() -> bytes:
    # RIFF 头 + 一点 PCM；内容合法性不重要（路由只看扩展名 + 大小）
    return b"RIFF\x00\x00\x00\x00WAVEfmt " + b"\x00" * 16


def _post(client, *, filename: str, data: dict | None = None, extra_headers: dict | None = None):
    data = dict(data or {})
    data.setdefault("target_lang", "zh")
    return client.post(
        "/api/video-translate",
        files={"source_file": (filename, io.BytesIO(_fake_audio_bytes()), "audio/wav")},
        data=data,
        headers=extra_headers or {},
    )


# ---------- 合法路径 ----------

def test_submit_audio_legal_returns_202_and_writes_job(client):
    _seed_llm(client, is_default=True)
    # 默认 TTS 是 Piper（不支持 clone），所以 clone_voice=false 才合法
    r = _post(client, filename="sample.wav", data={"clone_voice": "false"})
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["status"] == "pending"
    job_id = body["job_id"]

    # 提交后 run_job 后台 task 可能已启动并改变状态；只验证持久化元数据
    with Session(get_engine()) as s:
        job = s.get(Job, job_id)
        assert job is not None
        assert job.kind == "video_translate"
        assert job.status in {"pending", "running", "failed"}
        assert job.request["target_lang"] == "zh"
        assert job.request["source_is_video"] is False
        assert job.request["clone_voice"] is False
        assert job.source_path is not None


def test_submit_with_clone_voice_uses_cloning_default(client):
    """clone_voice=true + 未指定 tts_provider_id：
    应优先命中 kind=cloning 的 default（VoxCPM 支持克隆），不报错。"""
    _seed_llm(client, is_default=True)
    r = _post(client, filename="sample.wav", data={"clone_voice": "true"})
    assert r.status_code == 202, r.text


def test_submit_video_input_carries_is_video_flag(client):
    _seed_llm(client, is_default=True)
    r = _post(client, filename="clip.mp4", data={"clone_voice": "false"})
    assert r.status_code == 202
    job_id = r.json()["job_id"]
    with Session(get_engine()) as s:
        job = s.get(Job, job_id)
        assert job.request["source_is_video"] is True


# ---------- 验证规则：文件 ----------

def test_reject_unsupported_extension(client):
    _seed_llm(client, is_default=True)
    r = _post(client, filename="evil.exe", data={"clone_voice": "false"})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "INVALID_MEDIA"


def test_reject_upload_too_large_via_content_length(client):
    _seed_llm(client, is_default=True)
    # 超过默认 2 GiB：传一个巨大的 Content-Length，路由预检就应拒绝
    huge = 3 * 1024**3
    r = _post(
        client, filename="sample.wav",
        data={"clone_voice": "false"},
        extra_headers={"content-length": str(huge)},
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "UPLOAD_TOO_LARGE"


# ---------- 验证规则：语言 ----------

def test_reject_invalid_target_lang(client):
    _seed_llm(client, is_default=True)
    r = _post(
        client, filename="sample.wav",
        data={"target_lang": "Chinese?!", "clone_voice": "false"},
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "INVALID_LANG"


def test_reject_invalid_source_lang(client):
    _seed_llm(client, is_default=True)
    r = _post(
        client, filename="sample.wav",
        data={"source_lang": "123", "clone_voice": "false"},
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "INVALID_LANG"


# ---------- 验证规则：枚举 / 范围（Pydantic 自动）----------

def test_reject_invalid_subtitle_mode(client):
    """Pydantic 级别枚举校验：RequestValidationError → 400 VALIDATION_ERROR（全局约定）。"""
    _seed_llm(client, is_default=True)
    r = _post(
        client, filename="clip.mp4",
        data={"subtitle_mode": "wat", "clone_voice": "false"},
    )
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"


def test_reject_invalid_align_mode(client):
    _seed_llm(client, is_default=True)
    r = _post(
        client, filename="sample.wav",
        data={"align_mode": "fast", "clone_voice": "false"},
    )
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"


def test_reject_align_max_speedup_out_of_range(client):
    _seed_llm(client, is_default=True)
    r = _post(
        client, filename="sample.wav",
        data={"align_max_speedup": "3.0", "clone_voice": "false"},
    )
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"


def test_reject_system_prompt_too_long(client):
    _seed_llm(client, is_default=True)
    r = _post(
        client, filename="sample.wav",
        data={"system_prompt": "x" * 2001, "clone_voice": "false"},
    )
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"


# ---------- 验证规则：Provider 存在性 / kind / capability ----------

def test_reject_asr_provider_not_found(client):
    _seed_llm(client, is_default=True)
    r = _post(
        client, filename="sample.wav",
        data={"asr_provider_id": "999999", "clone_voice": "false"},
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "PROVIDER_NOT_FOUND"


def test_reject_tts_provider_kind_mismatch(client):
    _seed_llm(client, is_default=True)
    # 把 ASR Provider 的 id 当作 tts_provider_id 传入
    asr_id = _get_provider_id("asr", "WhisperProvider")
    r = _post(
        client, filename="sample.wav",
        data={"tts_provider_id": str(asr_id), "clone_voice": "false"},
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "PROVIDER_NOT_FOUND"


def test_reject_clone_not_supported_when_explicit_tts_lacks_capability(client):
    """clone_voice=true + 显式指定不支持克隆的 Piper → 422 CLONE_NOT_SUPPORTED。"""
    _seed_llm(client, is_default=True)
    piper_id = _get_provider_id("tts", "PiperProvider")
    r = _post(
        client, filename="sample.wav",
        data={"tts_provider_id": str(piper_id), "clone_voice": "true"},
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "CLONE_NOT_SUPPORTED"


def test_reject_clone_not_supported_default(client):
    """删掉默认 cloning Provider 后，clone_voice=true + 未指定 tts_provider_id
    应回退到 default tts（Piper）不支持克隆 → 422 CLONE_NOT_SUPPORTED_DEFAULT。"""
    _seed_llm(client, is_default=True)
    # 把 cloning 默认 Provider 禁用，让 default_tts 回退到 Piper
    from sqlmodel import select
    with Session(get_engine()) as s:
        row = s.exec(
            select(Provider).where(Provider.kind == "cloning")
        ).first()
        assert row is not None
        row.enabled = False
        s.add(row)
        s.commit()

    r = _post(client, filename="sample.wav", data={"clone_voice": "true"})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "CLONE_NOT_SUPPORTED_DEFAULT"
    # 错误 body 应含可用克隆 Provider 候选（此时为空，因我们禁用了唯一一个）
    assert "clone_capable_provider_ids" in r.json()["error"]["details"]


# ---------- 验证规则：LLM ----------

def test_reject_llm_not_configured_when_no_default(client):
    # 故意不 seed LLM
    r = _post(client, filename="sample.wav", data={"clone_voice": "false"})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "LLM_NOT_CONFIGURED"


def test_reject_llm_provider_not_found(client):
    _seed_llm(client, is_default=True)
    r = _post(
        client, filename="sample.wav",
        data={"clone_voice": "false", "llm_provider_id": "999999"},
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "PROVIDER_NOT_FOUND"


def test_accept_custom_llm_provider_id(client):
    """显式传 llm_provider_id（非默认）应能通过。"""
    created = _seed_llm(client, is_default=False)
    r = _post(
        client, filename="sample.wav",
        data={"clone_voice": "false", "llm_provider_id": str(created["id"])},
    )
    assert r.status_code == 202
