"""MoonshineProvider 单元测试（mock moonshine_onnx，不实际下载模型）。"""
from __future__ import annotations

import sys
from types import ModuleType
from pathlib import Path

import pytest

from voxcraft.errors import InferenceError, ModelLoadError
from voxcraft.providers.asr.moonshine import MoonshineProvider


@pytest.fixture
def mock_moonshine(monkeypatch):
    """注入 mock moonshine_onnx + onnxruntime 模块，避免真实下载/推理。"""
    captured: dict = {}

    fake_mod = ModuleType("moonshine_onnx")

    def fake_transcribe(audio_path, model_name, **kwargs):
        captured["audio_path"] = audio_path
        captured["model_name"] = model_name
        captured["kwargs"] = kwargs
        # Moonshine 返回 list[str]——多句串联
        return ["你好世界", "second sentence"]

    fake_mod.transcribe = fake_transcribe  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "moonshine_onnx", fake_mod)

    # mock onnxruntime.get_available_providers 让 device='cuda' 能通过
    fake_ort = ModuleType("onnxruntime")
    fake_ort.get_available_providers = lambda: [  # type: ignore[attr-defined]
        "CUDAExecutionProvider", "CPUExecutionProvider",
    ]
    monkeypatch.setitem(sys.modules, "onnxruntime", fake_ort)
    return captured


@pytest.fixture
def fake_wav(tmp_path: Path) -> str:
    """构造一个最小可读的 WAV（1s 静音）；soundfile.info 能读出 samplerate / frames。"""
    import wave
    p = tmp_path / "fake.wav"
    with wave.open(str(p), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00\x00" * 16000)  # 1s 静音
    return str(p)


def test_load_marks_loaded(mock_moonshine):  # noqa: ARG001
    p = MoonshineProvider(name="m", config={"model_name": "moonshine/base"})
    assert not p.loaded
    p.load()
    assert p.loaded
    assert p._model_name == "moonshine/base"


def test_load_without_library_raises(monkeypatch):
    monkeypatch.setitem(sys.modules, "moonshine_onnx", None)
    p = MoonshineProvider(name="m", config={"model_name": "moonshine/base"})
    with pytest.raises(ModelLoadError) as exc:
        p.load()
    assert "moonshine_onnx" in exc.value.message


def test_load_device_cuda_when_unavailable_raises(monkeypatch):
    """device='cuda' 但 onnxruntime 没 CUDA EP → ModelLoadError。"""
    monkeypatch.setitem(sys.modules, "moonshine_onnx", ModuleType("moonshine_onnx"))
    fake_ort = ModuleType("onnxruntime")
    fake_ort.get_available_providers = lambda: ["CPUExecutionProvider"]  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "onnxruntime", fake_ort)
    p = MoonshineProvider(name="m", config={"model_name": "moonshine/base", "device": "cuda"})
    with pytest.raises(ModelLoadError) as exc:
        p.load()
    assert "CUDA" in exc.value.message


def test_transcribe_returns_single_segment(mock_moonshine, fake_wav):
    p = MoonshineProvider(
        name="m",
        config={"model_name": "moonshine/base-zh", "language": "zh"},
    )
    p.load()
    r = p.transcribe(fake_wav, language="zh")

    # 单段 [0, duration] 覆盖整段（Moonshine 不返回 segment 级时间戳）
    assert len(r.segments) == 1
    seg = r.segments[0]
    assert seg.start == 0.0
    assert seg.end > 0.0      # duration probed from WAV
    assert "你好世界" in seg.text
    assert "second sentence" in seg.text
    assert r.language == "zh"
    assert r.duration > 0.0

    # 调用透传
    assert mock_moonshine["audio_path"] == fake_wav
    assert mock_moonshine["model_name"] == "moonshine/base-zh"


def test_transcribe_max_tokens_per_second_passes_through(mock_moonshine, fake_wav):
    p = MoonshineProvider(
        name="m",
        config={"model_name": "moonshine/base-zh", "max_tokens_per_second": "13.0"},
    )
    p.load()
    p.transcribe(fake_wav)
    assert mock_moonshine["kwargs"].get("max_tokens_per_second") == 13.0


def test_transcribe_options_override_config(mock_moonshine, fake_wav):
    """options['model_name'] 优先于 self.config['model_name']。"""
    p = MoonshineProvider(name="m", config={"model_name": "moonshine/base"})
    p.load()
    p.transcribe(fake_wav, options={"model_name": "moonshine/tiny"})
    assert mock_moonshine["model_name"] == "moonshine/tiny"


def test_transcribe_falls_back_when_kwarg_unsupported(monkeypatch, fake_wav):
    """旧版 moonshine_onnx 不接受 max_tokens_per_second → 自动 fallback 不带它再试。"""
    fake_mod = ModuleType("moonshine_onnx")
    call_count = {"n": 0}

    def fake_transcribe(audio_path, model_name, **kwargs):
        call_count["n"] += 1
        if kwargs:
            # 模拟旧版本拒绝未知 kwarg
            raise TypeError(f"unexpected keyword: {list(kwargs)}")
        return ["fallback ok"]

    fake_mod.transcribe = fake_transcribe  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "moonshine_onnx", fake_mod)
    fake_ort = ModuleType("onnxruntime")
    fake_ort.get_available_providers = lambda: ["CPUExecutionProvider"]  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "onnxruntime", fake_ort)

    p = MoonshineProvider(
        name="m",
        config={"model_name": "moonshine/base", "max_tokens_per_second": "13.0"},
    )
    p.load()
    r = p.transcribe(fake_wav)
    assert call_count["n"] == 2  # 第一次带 kwarg 失败，第二次裸调用
    assert "fallback" in r.segments[0].text


def test_transcribe_progress_cb_called_once(mock_moonshine, fake_wav):  # noqa: ARG001
    calls: list[float] = []
    p = MoonshineProvider(name="m", config={"model_name": "moonshine/base"})
    p.load()
    p.transcribe(fake_wav, progress_cb=lambda x: calls.append(x))
    # Moonshine 无 segment 级进度，最终汇报 1.0
    assert calls == [1.0]


def test_unload_resets_state(mock_moonshine, fake_wav):  # noqa: ARG001
    p = MoonshineProvider(name="m", config={"model_name": "moonshine/base"})
    p.load()
    assert p.loaded
    p.unload()
    assert not p.loaded
    assert p._model_name is None


def test_info_reports_resolved_providers(mock_moonshine):  # noqa: ARG001
    p = MoonshineProvider(
        name="m",
        config={"model_name": "moonshine/tiny", "device": "auto"},
    )
    p.load()
    info = p.info()
    assert info.kind == "asr"
    assert info.class_name == "MoonshineProvider"
    assert info.extra["model_name"] == "moonshine/tiny"
    # auto + CUDA 可用 → 优先 CUDA EP
    assert info.extra["providers"][0] == "CUDAExecutionProvider"


def test_transcribe_handles_str_return(monkeypatch, fake_wav):
    """库返回 str 而非 list 的兼容路径。"""
    fake_mod = ModuleType("moonshine_onnx")
    fake_mod.transcribe = lambda audio_path, model_name, **kwargs: "纯字符串结果"  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "moonshine_onnx", fake_mod)
    fake_ort = ModuleType("onnxruntime")
    fake_ort.get_available_providers = lambda: ["CPUExecutionProvider"]  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "onnxruntime", fake_ort)

    p = MoonshineProvider(name="m", config={"model_name": "moonshine/base"})
    p.load()
    r = p.transcribe(fake_wav)
    assert r.segments[0].text == "纯字符串结果"


def test_transcribe_propagates_failure(monkeypatch, fake_wav):
    fake_mod = ModuleType("moonshine_onnx")

    def boom(*a, **kw):
        raise RuntimeError("onnx session blew up")
    fake_mod.transcribe = boom  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "moonshine_onnx", fake_mod)
    fake_ort = ModuleType("onnxruntime")
    fake_ort.get_available_providers = lambda: ["CPUExecutionProvider"]  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "onnxruntime", fake_ort)

    p = MoonshineProvider(name="m", config={"model_name": "moonshine/base"})
    p.load()
    with pytest.raises(InferenceError) as exc:
        p.transcribe(fake_wav)
    assert "blew up" in exc.value.message
