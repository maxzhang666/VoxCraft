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
        def transcribe(self, audio_path, language=None, **kwargs):  # noqa: ARG002
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
        def transcribe(self, audio_path, language=None, **kwargs):  # noqa: ARG002
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
        def transcribe(self, audio_path, language=None, **kwargs):  # noqa: ARG002
            segs = [SimpleNamespace(start=0.0, end=1.0, text="Hello")]
            info = SimpleNamespace(language="en", duration=1.0)
            return iter(segs), info

    p._model = _FakeModel()
    p._loaded = True

    r = p.transcribe("any.wav", language="en")
    assert r.segments[0].text == "Hello"


def test_transcribe_options_override_config_defaults():
    """options 优先级高于 Provider config；缺失则回退 config；config 缺失再回退库默认。"""
    from types import SimpleNamespace

    captured: dict = {}

    p = WhisperProvider(
        name="w",
        config={
            "model_path": "/x",
            "beam_size": 7,            # config 默认 7
            "vad_filter": "true",       # config 开 VAD
        },
    )

    class _FakeModel:
        def transcribe(self, audio_path, language=None, **kwargs):  # noqa: ARG002
            captured.update(kwargs)
            info = SimpleNamespace(language="en", duration=1.0)
            return iter([SimpleNamespace(start=0.0, end=1.0, text="x")]), info

    p._model = _FakeModel()
    p._loaded = True

    # 请求级 options 覆盖 beam_size；vad_filter 不传 → 取 config 的 true；
    # temperature 都没设 → 库默认 0.0
    p.transcribe(
        "any.wav",
        options={"beam_size": 12, "initial_prompt": "code review"},
    )

    assert captured["beam_size"] == 12       # options override
    assert captured["vad_filter"] is True     # config fallback
    assert captured["temperature"] == 0.0     # library default
    assert captured["initial_prompt"] == "code review"


def test_transcribe_word_timestamps_attaches_words():
    """word_timestamps=True 时，segment 上挂 .words 列表，runner 端能读到。"""
    from types import SimpleNamespace

    p = WhisperProvider(name="w", config={"model_path": "/x"})

    fake_word = SimpleNamespace(start=0.0, end=0.5, word="hi", probability=0.9)

    class _FakeModel:
        def transcribe(self, audio_path, language=None, **kwargs):  # noqa: ARG002
            seg = SimpleNamespace(start=0.0, end=1.0, text="hi", words=[fake_word])
            return iter([seg]), SimpleNamespace(language="en", duration=1.0)

    p._model = _FakeModel()
    p._loaded = True

    r = p.transcribe("any.wav", options={"word_timestamps": True})
    seg = r.segments[0]
    words = getattr(seg, "words", None)
    assert words is not None
    assert words[0]["word"] == "hi"
    assert words[0]["start"] == 0.0
