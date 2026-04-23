"""PiperProvider 单元测试（不加载真模型）。"""
from __future__ import annotations

import pytest

from voxcraft.errors import InferenceError, ModelLoadError
from voxcraft.providers.tts.piper import PiperProvider


def test_construction_does_not_load():
    p = PiperProvider(name="piper", config={"model": "/nonexistent"})
    assert p.name == "piper"
    assert p.loaded is False
    assert p.info().class_name == "PiperProvider"


def test_load_missing_model_field_raises():
    p = PiperProvider(name="p", config={})
    with pytest.raises(ModelLoadError) as exc:
        p.load()
    assert exc.value.code == "MODEL_LOAD_ERROR"


def test_load_nonexistent_path_raises():
    p = PiperProvider(name="p", config={"model": "/definitely/not/real.onnx"})
    with pytest.raises(ModelLoadError):
        p.load()
    assert p.loaded is False


def test_synthesize_before_load_raises():
    p = PiperProvider(name="p", config={"model": "/x"})
    with pytest.raises(InferenceError) as exc:
        p.synthesize("hi", voice_id="p")
    assert exc.value.code == "INFERENCE_ERROR"


def test_list_voices_single_entry():
    p = PiperProvider(name="piper-zh", config={"model": "/x"})
    voices = p.list_voices()
    assert len(voices) == 1
    assert voices[0].id == "piper-zh"
    assert voices[0].language == "zh"
