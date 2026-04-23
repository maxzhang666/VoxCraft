"""Provider 抽象契约与 Mock 行为验证。"""
from __future__ import annotations

import pytest

from voxcraft.providers.base import (
    AsrProvider,
    AsrResult,
    CloningProvider,
    Provider,
    SeparatorProvider,
    TranslationProvider,
    TtsProvider,
)
from voxcraft.providers.mock import (
    InMemoryMockAsrProvider,
    InMemoryMockSeparatorProvider,
    InMemoryMockTtsProvider,
)


def test_abstract_provider_not_instantiable():
    with pytest.raises(TypeError):
        Provider(name="x", config={})  # type: ignore[abstract]


def test_abstract_subclasses_not_instantiable():
    for cls in (AsrProvider, TtsProvider, CloningProvider, SeparatorProvider, TranslationProvider):
        with pytest.raises(TypeError):
            cls(name="x", config={})  # type: ignore[abstract]


def test_kind_classvar_fixed():
    assert AsrProvider.kind == "asr"
    assert TtsProvider.kind == "tts"
    assert CloningProvider.kind == "cloning"
    assert SeparatorProvider.kind == "separator"
    assert TranslationProvider.kind == "translation"


def test_mock_asr_lifecycle():
    p = InMemoryMockAsrProvider(name="mock", config={})
    assert p.loaded is False

    p.load()
    assert p.loaded is True

    result = p.transcribe("any.wav", language="zh")
    assert isinstance(result, AsrResult)
    assert result.language == "zh"
    assert result.segments[0].text == "mock text"

    p.unload()
    assert p.loaded is False


def test_mock_tts_and_separator():
    tts = InMemoryMockTtsProvider(name="m", config={})
    tts.load()
    audio = tts.synthesize("hello", voice_id="mock-voice")
    assert audio.startswith(b"RIFF")
    assert tts.list_voices()[0].id == "mock-voice"

    sep = InMemoryMockSeparatorProvider(name="m", config={})
    sep.load()
    r = sep.separate("any.wav")
    assert r.vocals_path.endswith(".wav")
