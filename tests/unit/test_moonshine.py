"""MoonshineProvider 单元测试（mock moonshine_voice 的 batch API）。

聚焦：load 流程、language 校验、batch 转写、WAV / 非 WAV 输入、错误透传。
不真下载模型，不真跑 ONNX 推理。
"""
from __future__ import annotations

import sys
import wave
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from voxcraft.errors import InferenceError, ModelLoadError
from voxcraft.providers.asr.moonshine import MoonshineProvider


@pytest.fixture
def fake_wav(tmp_path: Path) -> str:
    p = tmp_path / "fake.wav"
    with wave.open(str(p), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00\x00" * 16000)
    return str(p)


class _FakeTranscriber:
    """模拟 moonshine_voice.Transcriber 的 batch 子集。"""

    def __init__(self, model_path, model_arch, update_interval=0.5):  # noqa: ARG002
        self.model_path = model_path
        self.model_arch = model_arch
        self.last_audio = None
        self.last_sample_rate = None
        # 默认返回两行带 word timing 的 Transcript
        self._lines = [
            SimpleNamespace(
                text="你好世界",
                start_time=0.0,
                duration=1.0,
                words=[
                    SimpleNamespace(word="你好", start=0.0, end=0.5, confidence=0.95),
                    SimpleNamespace(word="世界", start=0.5, end=1.0, confidence=0.92),
                ],
            ),
            SimpleNamespace(
                text="第二句",
                start_time=1.2,
                duration=0.8,
                words=None,
            ),
        ]

    def transcribe_without_streaming(self, audio_data, sample_rate=16000, flags=0):  # noqa: ARG002
        self.last_audio = audio_data
        self.last_sample_rate = sample_rate
        return SimpleNamespace(lines=self._lines)

    def close(self) -> None:
        pass


@pytest.fixture
def mock_moonshine_voice(monkeypatch):
    captured: dict = {}

    fake_mod = ModuleType("moonshine_voice")

    def fake_get_model(lang):
        captured["language"] = lang
        return (f"/fake/path/{lang}", f"arch-{lang}")

    fake_mod.get_model_for_language = fake_get_model  # type: ignore[attr-defined]
    fake_mod.Transcriber = _FakeTranscriber  # type: ignore[attr-defined]
    fake_mod.load_wav_file = lambda p: ([0.0] * 16000, 16000)  # type: ignore[attr-defined]
    fake_mod.model_arch_to_string = lambda arch: f"str:{arch}"  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "moonshine_voice", fake_mod)

    fake_ort = ModuleType("onnxruntime")
    fake_ort.get_available_providers = lambda: [  # type: ignore[attr-defined]
        "CUDAExecutionProvider", "CPUExecutionProvider",
    ]
    monkeypatch.setitem(sys.modules, "onnxruntime", fake_ort)
    return captured


def test_load_resolves_language(mock_moonshine_voice):
    p = MoonshineProvider(name="m", config={"language": "zh"})
    p.load()
    assert p.loaded
    assert p._language == "zh"
    assert mock_moonshine_voice["language"] == "zh"


def test_load_without_library_raises(monkeypatch):
    monkeypatch.setitem(sys.modules, "moonshine_voice", None)
    p = MoonshineProvider(name="m", config={"language": "en"})
    with pytest.raises(ModelLoadError) as exc:
        p.load()
    assert "moonshine_voice" in exc.value.message


def test_load_unsupported_language_raises(monkeypatch):
    fake_mod = ModuleType("moonshine_voice")

    def bad(lang):
        raise ValueError(f"unsupported language {lang}")
    fake_mod.get_model_for_language = bad  # type: ignore[attr-defined]
    fake_mod.Transcriber = _FakeTranscriber  # type: ignore[attr-defined]
    fake_mod.model_arch_to_string = str  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "moonshine_voice", fake_mod)

    p = MoonshineProvider(name="m", config={"language": "klingon"})
    with pytest.raises(ModelLoadError) as exc:
        p.load()
    assert "klingon" in exc.value.message


def test_transcribe_returns_segments_and_word_timings(mock_moonshine_voice, fake_wav):
    p = MoonshineProvider(name="m", config={"language": "zh"})
    p.load()
    r = p.transcribe(fake_wav)

    assert len(r.segments) == 2
    s0 = r.segments[0]
    assert s0.text == "你好世界"
    assert s0.start == 0.0
    assert s0.end == 1.0
    assert getattr(s0, "words", None) == [
        {"start": 0.0, "end": 0.5, "word": "你好", "probability": 0.95},
        {"start": 0.5, "end": 1.0, "word": "世界", "probability": 0.92},
    ]

    s1 = r.segments[1]
    assert s1.text == "第二句"
    assert s1.start == 1.2
    assert s1.end == 2.0
    assert not hasattr(s1, "words")  # 第二行没有 words

    assert r.language == "zh"
    assert r.duration > 0


def test_transcribe_passes_audio_and_sample_rate(mock_moonshine_voice, fake_wav):
    p = MoonshineProvider(name="m", config={"language": "en"})
    p.load()
    p.transcribe(fake_wav)
    # _FakeTranscriber captures last audio + sr
    transcriber = p._transcriber  # type: ignore[attr-defined]
    assert transcriber.last_audio == [0.0] * 16000
    assert transcriber.last_sample_rate == 16000


def test_transcribe_progress_callback(mock_moonshine_voice, fake_wav):
    p = MoonshineProvider(name="m", config={"language": "en"})
    p.load()
    calls: list[float] = []
    p.transcribe(fake_wav, progress_cb=lambda x: calls.append(x))
    assert calls == [1.0]


def test_transcribe_non_wav_input_goes_through_ffmpeg(
    monkeypatch, mock_moonshine_voice, tmp_path,  # noqa: ARG001
):
    src = tmp_path / "video.mp4"
    src.write_bytes(b"not a wav header")
    extract_calls: list[tuple[str, str]] = []

    def fake_extract_audio(src_path, dst_path, **kwargs):  # noqa: ARG001
        with wave.open(str(dst_path), "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
            w.writeframes(b"\x00\x00" * 16000)
        extract_calls.append((str(src_path), str(dst_path)))
        return dst_path

    monkeypatch.setattr(
        "voxcraft.video.ffmpeg_io.extract_audio", fake_extract_audio,
    )

    p = MoonshineProvider(name="m", config={"language": "en"})
    p.load()
    r = p.transcribe(str(src))
    assert len(extract_calls) == 1
    assert extract_calls[0][0] == str(src)
    assert r.segments[0].text  # 拿到了文本


def test_transcribe_empty_lines_yields_empty_segment(monkeypatch, fake_wav):
    """transcribe 返回 lines=[] 时 → 单个空 segment（不 crash）。"""
    class _EmptyTranscriber(_FakeTranscriber):
        def transcribe_without_streaming(self, audio_data, sample_rate=16000, flags=0):  # noqa: ARG002
            return SimpleNamespace(lines=[])

    fake_mod = ModuleType("moonshine_voice")
    fake_mod.get_model_for_language = lambda l: (f"/p/{l}", f"a-{l}")  # type: ignore[attr-defined]
    fake_mod.Transcriber = _EmptyTranscriber  # type: ignore[attr-defined]
    fake_mod.load_wav_file = lambda p: ([0.0] * 1000, 16000)  # type: ignore[attr-defined]
    fake_mod.model_arch_to_string = str  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "moonshine_voice", fake_mod)
    monkeypatch.setitem(sys.modules, "onnxruntime", ModuleType("onnxruntime"))

    p = MoonshineProvider(name="m", config={"language": "en"})
    p.load()
    r = p.transcribe(fake_wav)
    assert len(r.segments) == 1
    assert r.segments[0].text == ""


def test_transcribe_propagates_failure(monkeypatch, fake_wav):
    class _BoomTranscriber(_FakeTranscriber):
        def transcribe_without_streaming(self, audio_data, sample_rate=16000, flags=0):  # noqa: ARG002
            raise RuntimeError("inference blew up")

    fake_mod = ModuleType("moonshine_voice")
    fake_mod.get_model_for_language = lambda l: (f"/p/{l}", f"a-{l}")  # type: ignore[attr-defined]
    fake_mod.Transcriber = _BoomTranscriber  # type: ignore[attr-defined]
    fake_mod.load_wav_file = lambda p: ([0.0] * 1000, 16000)  # type: ignore[attr-defined]
    fake_mod.model_arch_to_string = str  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "moonshine_voice", fake_mod)
    monkeypatch.setitem(sys.modules, "onnxruntime", ModuleType("onnxruntime"))

    p = MoonshineProvider(name="m", config={"language": "en"})
    p.load()
    with pytest.raises(InferenceError) as exc:
        p.transcribe(fake_wav)
    assert "blew up" in exc.value.message


def test_unload_resets_state(mock_moonshine_voice, fake_wav):  # noqa: ARG001
    p = MoonshineProvider(name="m", config={"language": "en"})
    p.load()
    assert p.loaded
    p.unload()
    assert not p.loaded
    assert p._transcriber is None
    assert p._language is None


def test_info_reports_language_and_ort_providers(mock_moonshine_voice):  # noqa: ARG001
    p = MoonshineProvider(name="m", config={"language": "ja", "device": "auto"})
    p.load()
    info = p.info()
    assert info.kind == "asr"
    assert info.class_name == "MoonshineProvider"
    assert info.extra["language"] == "ja"
    assert "CUDAExecutionProvider" in info.extra["ort_providers"]
    assert info.extra["model_arch"].startswith("str:")
