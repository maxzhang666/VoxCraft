"""WhisperProvider 单元测试（不加载真模型，仅覆盖关键分支）。"""
from __future__ import annotations

import pytest

from voxcraft.errors import InferenceError, ModelLoadError
from voxcraft.providers.asr.whisper import WhisperProvider


def test_construction_does_not_load():
    p = WhisperProvider(name="w", config={"model_path": "/nonexistent"})
    assert p.name == "w"
    assert p.loaded is False
    assert p.info().loaded is False
    assert p.info().class_name == "WhisperProvider"


def test_load_missing_model_path_raises():
    p = WhisperProvider(name="w", config={})
    with pytest.raises(ModelLoadError) as exc:
        p.load()
    assert exc.value.code == "MODEL_LOAD_ERROR"


def test_load_nonexistent_path_raises():
    p = WhisperProvider(
        name="w",
        config={"model_path": "/definitely/not/a/real/path-xyz-123"},
    )
    with pytest.raises(ModelLoadError):
        p.load()
    assert p.loaded is False


def test_transcribe_before_load_raises():
    p = WhisperProvider(name="w", config={"model_path": "/x"})
    with pytest.raises(InferenceError) as exc:
        p.transcribe("any.wav")
    assert exc.value.code == "INFERENCE_ERROR"


def test_unload_is_idempotent():
    p = WhisperProvider(name="w", config={"model_path": "/x"})
    p.unload()
    p.unload()
    assert p.loaded is False
