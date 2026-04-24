"""视频语音级翻译 E2E（slow 标记，需真模型，ADR-014 / v0.4.0）。

触发：`pytest -m slow tests/e2e/test_video_translate_e2e.py`

环境变量：
- `WHISPER_TEST_MODEL`：faster-whisper 模型路径或 HF id（如 `Systran/faster-whisper-small`）
- `PIPER_TEST_MODEL`：Piper ONNX 模型文件路径
- 其一缺失即 skip（不拦截 CI）

LLM 被 mock 注入（不依赖外部 API），其余链路（ASR / TTS / ffmpeg）走真实实现。
验证：三路产物生成、SRT 内容、产物时长合理。
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from voxcraft.runtime.scheduler_api import JobRequest
from voxcraft.runtime.worker_runners import _LruOne
from voxcraft.video.alignment import wav_duration
from voxcraft.video.orchestrator import run_video_translate


pytestmark = pytest.mark.slow


def _skip_if_missing_models() -> tuple[str, str]:
    whisper_model = os.environ.get("WHISPER_TEST_MODEL")
    piper_model = os.environ.get("PIPER_TEST_MODEL")
    if not whisper_model:
        pytest.skip("WHISPER_TEST_MODEL not set")
    if not piper_model or not Path(piper_model).exists():
        pytest.skip("PIPER_TEST_MODEL not set or file missing")
    if shutil.which("ffmpeg") is None:
        pytest.skip("system ffmpeg not available")
    return whisper_model, piper_model


@pytest.fixture
def real_audio_clip(tmp_path: Path) -> Path:
    """3 秒人声样本（用 espeak-ng 或 Piper 合成；本地没这些时用静音占位）。

    这里用 ffmpeg 生成 3 秒静音——Whisper 会返回空 segments，测试能跑通但
    无法验证翻译内容。更有意义的 fixture 需要部署方提供真录音，可通过
    `VIDEO_TRANSLATE_E2E_SAMPLE` 环境变量指定。
    """
    override = os.environ.get("VIDEO_TRANSLATE_E2E_SAMPLE")
    if override and Path(override).exists():
        return Path(override)
    out = tmp_path / "silent.wav"
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono", "-t", "3",
            str(out),
        ],
        check=True,
    )
    return out


def _make_req(
    source: Path,
    out_dir: Path,
    *,
    whisper_model: str,
    piper_model: str,
) -> JobRequest:
    return JobRequest(
        job_id="e2e-video-translate",
        kind="video_translate",
        provider_name="video-translate",
        class_name="VideoTranslateOrchestrator",
        provider_config={},
        request_meta={
            "asr": {
                "class_name": "WhisperProvider",
                "name": "whisper-test",
                "config": {
                    "model_path": whisper_model,
                    "compute_type": "int8",
                    "device": "auto",
                },
            },
            "tts": {
                "class_name": "PiperProvider",
                "name": "piper-test",
                "config": {"model": piper_model},
            },
            "llm": {"base_url": "mock", "api_key": "sk-mock", "model": "mock"},
            "target_lang": "zh",
            "source_lang": "en",
            "subtitle_mode": "none",
            "clone_voice": False,
            "align_mode": "natural",
            "align_max_speedup": 1.3,
            "system_prompt": None,
        },
        source_path=str(source),
        output_dir=str(out_dir),
    )


def _mock_llm(messages, *, model=None):  # noqa: ANN001
    # 简单按长度生成中文译文
    src = messages[-1]["content"]
    return f"[译] {src[:40]}"


def test_video_translate_real_models_audio_input(real_audio_clip, tmp_path):
    whisper_model, piper_model = _skip_if_missing_models()

    req = _make_req(
        real_audio_clip, tmp_path,
        whisper_model=whisper_model, piper_model=piper_model,
    )
    result = run_video_translate(req, _LruOne(), emit=None, llm_chat_fn=_mock_llm)

    # 即便 ASR 产出空 segments（静音源），orchestrator 应报 INFERENCE_ERROR
    # 而不是 crash。真录音样本（VIDEO_TRANSLATE_E2E_SAMPLE）下才能验证正常路径。
    if not result.ok:
        assert result.error_code in {"INFERENCE_ERROR", "INTERNAL_ERROR"}
        return

    # 正常路径断言
    extras = result.output_extras
    assert extras is not None
    assert Path(extras["subtitle"]).exists()
    assert Path(extras["audio"]).exists()
    assert "video" not in extras  # 音频输入

    # 译文音频非空且可被 wave 读取
    duration = wav_duration(extras["audio"])
    assert duration > 0.1

    srt = Path(extras["subtitle"]).read_text(encoding="utf-8")
    assert "[译]" in srt or "[untranslated]" in srt
