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


def test_simplify_chinese_converts_traditional():
    """中文 language=zh 时默认转简体。"""
    from voxcraft.providers.asr.whisper import _to_simplified

    # 繁体 → 简体（"當前" → "当前"；"識別" → "识别"）
    assert _to_simplified("當前識別") == "当前识别"


def test_simplify_chinese_skips_non_cjk():
    from voxcraft.providers.asr.whisper import _to_simplified

    # 纯英文不做处理（快速路径）
    assert _to_simplified("hello world") == "hello world"
    assert _to_simplified("") == ""


def test_simplify_chinese_preserves_simplified():
    from voxcraft.providers.asr.whisper import _to_simplified

    # 已是简体，无需改动
    assert _to_simplified("你好，世界") == "你好，世界"


def test_transcribe_applies_simplify_when_language_zh(monkeypatch):
    """mock faster-whisper：language=zh 时繁体被转简体。"""
    from types import SimpleNamespace

    p = WhisperProvider(name="w", config={"model_path": "/x"})

    class _FakeModel:
        def transcribe(self, audio_path, language=None):  # noqa: ARG002
            segs = [SimpleNamespace(start=0.0, end=1.0, text="當前識別結果")]
            info = SimpleNamespace(language="zh", duration=1.0)
            return iter(segs), info

    p._model = _FakeModel()
    p._loaded = True

    r = p.transcribe("any.wav", language="zh")
    assert r.segments[0].text == "当前识别结果"


def test_transcribe_skips_simplify_when_disabled(monkeypatch):
    from types import SimpleNamespace

    p = WhisperProvider(
        name="w",
        config={"model_path": "/x", "simplify_chinese": "false"},
    )

    class _FakeModel:
        def transcribe(self, audio_path, language=None):  # noqa: ARG002
            segs = [SimpleNamespace(start=0.0, end=1.0, text="當前")]
            info = SimpleNamespace(language="zh", duration=1.0)
            return iter(segs), info

    p._model = _FakeModel()
    p._loaded = True

    r = p.transcribe("any.wav", language="zh")
    # 关闭后保留繁体原样
    assert r.segments[0].text == "當前"


def test_transcribe_skips_simplify_for_non_chinese(monkeypatch):
    from types import SimpleNamespace

    p = WhisperProvider(name="w", config={"model_path": "/x"})

    class _FakeModel:
        def transcribe(self, audio_path, language=None):  # noqa: ARG002
            segs = [SimpleNamespace(start=0.0, end=1.0, text="Hello")]
            info = SimpleNamespace(language="en", duration=1.0)
            return iter(segs), info

    p._model = _FakeModel()
    p._loaded = True

    r = p.transcribe("any.wav", language="en")
    assert r.segments[0].text == "Hello"
