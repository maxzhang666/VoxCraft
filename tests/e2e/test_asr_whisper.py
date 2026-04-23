"""WhisperProvider 真实模型加载验证（slow 标记，默认跳过）。

触发：`pytest -m slow`
依赖：
- 网络连通（首次从 HF Hub 拉 tiny 模型）
- 可选环境变量 `WHISPER_TEST_MODEL`（默认 Systran/faster-whisper-tiny）
- 可选环境变量 `WHISPER_TEST_AUDIO`（音频测试样本路径）
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from voxcraft.providers.asr.whisper import WhisperProvider

pytestmark = pytest.mark.slow


@pytest.fixture
def whisper():
    p = WhisperProvider(
        name="test-tiny",
        config={
            "model_path": os.environ.get(
                "WHISPER_TEST_MODEL", "Systran/faster-whisper-tiny"
            ),
            "compute_type": "int8",
            "device": "cpu",
        },
    )
    p.load()
    yield p
    p.unload()


def test_load_and_info(whisper):
    assert whisper.loaded is True
    info = whisper.info()
    assert info.kind == "asr"
    assert info.loaded is True


def test_transcribe_sample(whisper):
    audio = os.environ.get("WHISPER_TEST_AUDIO")
    if not audio or not Path(audio).exists():
        pytest.skip("WHISPER_TEST_AUDIO 未设置或文件不存在")
    result = whisper.transcribe(audio)
    assert result.duration > 0
    assert len(result.segments) > 0
    assert result.language
