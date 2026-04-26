"""GptSoVitsProvider 单元测试（mock GPT-SoVITS 包，不依赖真模型）。"""
from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType

import numpy as np
import pytest

from voxcraft.errors import InferenceError, ModelLoadError
from voxcraft.providers.cloning.gpt_sovits import GptSoVitsProvider


@pytest.fixture
def model_dir(tmp_path: Path) -> Path:
    """构造一个 v2Pro 标准目录结构（空文件占位即可，Provider 只检查存在性）。"""
    (tmp_path / "chinese-roberta-wwm-ext-large").mkdir()
    (tmp_path / "chinese-hubert-base").mkdir()
    (tmp_path / "s1v3.ckpt").touch()
    (tmp_path / "v2Pro").mkdir()
    (tmp_path / "v2Pro" / "s2Gv2Pro.pth").touch()
    (tmp_path / "v2Pro" / "s2Gv2ProPlus.pth").touch()
    return tmp_path


@pytest.fixture
def mock_gpt_sovits(monkeypatch):
    """注入 mock GPT_SoVITS.TTS_infer_pack.TTS 模块。"""
    captured: dict = {}

    class _FakeConfig:
        sampling_rate = 32000

    class _FakeTTS:
        def __init__(self, configs):
            captured["configs"] = configs
            self.configs = _FakeConfig()

        def run(self, inputs):
            captured["inputs"] = inputs
            # yield 两段静音，验证 chunk 拼接路径
            yield 32000, np.zeros(3200, dtype=np.int16)
            yield 32000, np.zeros(3200, dtype=np.int16)

    class _FakeTTSConfig:
        pass

    fake_tts_module = ModuleType("GPT_SoVITS.TTS_infer_pack.TTS")
    fake_tts_module.TTS = _FakeTTS
    fake_tts_module.TTS_Config = _FakeTTSConfig

    fake_pack_module = ModuleType("GPT_SoVITS.TTS_infer_pack")
    fake_root_module = ModuleType("GPT_SoVITS")

    monkeypatch.setitem(sys.modules, "GPT_SoVITS", fake_root_module)
    monkeypatch.setitem(sys.modules, "GPT_SoVITS.TTS_infer_pack", fake_pack_module)
    monkeypatch.setitem(sys.modules, "GPT_SoVITS.TTS_infer_pack.TTS", fake_tts_module)
    return captured


def test_load_passes_paths_to_tts(mock_gpt_sovits, model_dir: Path):
    p = GptSoVitsProvider(
        name="gs",
        config={"model_dir": str(model_dir), "version": "v2Pro", "device": "cpu"},
    )
    p.load()
    assert p.loaded is True

    cfg = mock_gpt_sovits["configs"]["custom"]
    assert cfg["bert_base_path"] == str(model_dir / "chinese-roberta-wwm-ext-large")
    assert cfg["cnhuhbert_base_path"] == str(model_dir / "chinese-hubert-base")
    assert cfg["t2s_weights_path"] == str(model_dir / "s1v3.ckpt")
    assert cfg["vits_weights_path"] == str(model_dir / "v2Pro" / "s2Gv2Pro.pth")
    assert cfg["version"] == "v2Pro"
    assert cfg["device"] == "cpu"
    assert cfg["is_half"] is False


def test_load_v2proplus_uses_plus_weights(mock_gpt_sovits, model_dir: Path):
    p = GptSoVitsProvider(
        name="gs",
        config={"model_dir": str(model_dir), "version": "v2ProPlus"},
    )
    p.load()
    cfg = mock_gpt_sovits["configs"]["custom"]
    assert cfg["vits_weights_path"] == str(model_dir / "v2Pro" / "s2Gv2ProPlus.pth")


def test_load_missing_files_raises(mock_gpt_sovits, tmp_path: Path):
    # 空目录，路径都不存在
    p = GptSoVitsProvider(name="gs", config={"model_dir": str(tmp_path)})
    with pytest.raises(ModelLoadError) as exc:
        p.load()
    assert "missing" in exc.value.message.lower()


def test_load_missing_model_dir_raises(mock_gpt_sovits):
    p = GptSoVitsProvider(name="gs", config={})
    with pytest.raises(ModelLoadError):
        p.load()


def test_load_without_package_raises(monkeypatch, model_dir: Path):
    # 模拟未装 GPT-SoVITS（chdir 不影响 import）
    monkeypatch.setitem(sys.modules, "GPT_SoVITS", None)
    monkeypatch.setitem(sys.modules, "GPT_SoVITS.TTS_infer_pack.TTS", None)
    p = GptSoVitsProvider(name="gs", config={"model_dir": str(model_dir)})
    with pytest.raises(ModelLoadError) as exc:
        p.load()
    assert "not installed" in exc.value.message.lower()


def test_synthesize_requires_reference_audio(mock_gpt_sovits, model_dir: Path):
    p = GptSoVitsProvider(
        name="gs",
        config={"model_dir": str(model_dir), "prompt_text": "hello"},
    )
    p.load()
    with pytest.raises(InferenceError) as exc:
        p.synthesize("你好", voice_id="gs_xxx")
    assert "reference_audio_path is required" in exc.value.message


def test_synthesize_requires_prompt_text(mock_gpt_sovits, model_dir: Path):
    p = GptSoVitsProvider(name="gs", config={"model_dir": str(model_dir)})
    p.load()
    with pytest.raises(InferenceError) as exc:
        p.synthesize(
            "你好", voice_id="gs_x", reference_audio_path="/r.wav",
        )
    assert "prompt_text" in exc.value.message.lower()


def test_synthesize_passes_inputs_and_returns_wav(mock_gpt_sovits, model_dir: Path):
    p = GptSoVitsProvider(
        name="gs",
        config={
            "model_dir": str(model_dir),
            "prompt_text": "Hello world",
            "prompt_lang": "en",
            "top_k": 20,
            "top_p": "0.9",
            "temperature": "0.8",
            "text_split_method": "cut3",
        },
    )
    p.load()
    out = p.synthesize(
        "你好世界",
        voice_id="gs_x",
        reference_audio_path="/data/ref.wav",
        speed=1.2,
    )
    assert isinstance(out, bytes)
    assert out.startswith(b"RIFF")

    inputs = mock_gpt_sovits["inputs"]
    assert inputs["text"] == "你好世界"
    assert inputs["text_lang"] == "zh"
    assert inputs["ref_audio_path"] == "/data/ref.wav"
    assert inputs["prompt_text"] == "Hello world"
    assert inputs["prompt_lang"] == "en"
    assert inputs["top_k"] == 20
    assert inputs["top_p"] == 0.9
    assert inputs["temperature"] == 0.8
    assert inputs["text_split_method"] == "cut3"
    assert inputs["speed_factor"] == 1.2


def test_synthesize_unsupported_format_raises(mock_gpt_sovits, model_dir: Path):
    p = GptSoVitsProvider(
        name="gs",
        config={"model_dir": str(model_dir), "prompt_text": "x"},
    )
    p.load()
    with pytest.raises(InferenceError):
        p.synthesize(
            "你好", voice_id="gs_x", format="mp3", reference_audio_path="/r.wav",
        )


def test_clone_voice_returns_gs_id(mock_gpt_sovits, model_dir: Path):
    p = GptSoVitsProvider(name="gs", config={"model_dir": str(model_dir)})
    p.load()
    vid = p.clone_voice("/r.wav", speaker_name="alice")
    assert vid.startswith("gs_")
    assert len(vid) == 3 + 12


def test_unload_resets_state(mock_gpt_sovits, model_dir: Path):
    p = GptSoVitsProvider(name="gs", config={"model_dir": str(model_dir)})
    p.load()
    assert p.loaded
    p.unload()
    assert p.loaded is False
    assert p._tts is None  # type: ignore[union-attr]


def test_info_reports_class_and_version(mock_gpt_sovits, model_dir: Path):
    p = GptSoVitsProvider(
        name="gs",
        config={"model_dir": str(model_dir), "version": "v2ProPlus"},
    )
    info = p.info()
    assert info.class_name == "GptSoVitsProvider"
    assert info.kind == "cloning"
    assert info.extra["version"] == "v2ProPlus"
