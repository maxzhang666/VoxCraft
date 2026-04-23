"""Piper 真实模型 E2E（slow 标记，需预下载 ONNX 模型）。

触发：`pytest -m slow tests/e2e/test_tts_piper.py`
环境变量：`PIPER_TEST_MODEL` 指向 .onnx 路径；未设置则跳过。
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from voxcraft.providers.tts.piper import PiperProvider

pytestmark = pytest.mark.slow


@pytest.fixture
def piper():
    model = os.environ.get("PIPER_TEST_MODEL")
    if not model or not Path(model).exists():
        pytest.skip("PIPER_TEST_MODEL 未设置或文件不存在")
    p = PiperProvider(name="piper-test", config={"model": model})
    p.load()
    yield p
    p.unload()


def test_synthesize_returns_wav_bytes(piper):
    audio = piper.synthesize("你好，世界", voice_id="piper-test")
    assert audio.startswith(b"RIFF"), "Expected WAV header"
    assert len(audio) > 1000, "Expected non-trivial audio bytes"


def test_speed_affects_length(piper):
    fast = piper.synthesize("测试语速", voice_id="x", speed=1.5)
    slow = piper.synthesize("测试语速", voice_id="x", speed=0.8)
    # speed 越快，WAV 越短（帧数少）
    assert len(fast) < len(slow)
