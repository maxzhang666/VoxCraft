"""VoxCpmCloningProvider 单元测试（mock voxcpm 包，不依赖真模型）。"""
from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace

import numpy as np
import pytest

from voxcraft.errors import InferenceError, ModelLoadError
from voxcraft.providers.cloning.voxcpm import VoxCpmCloningProvider


@pytest.fixture
def mock_voxcpm(monkeypatch):
    """注入一个 mock 的 voxcpm 模块；测试结束 monkeypatch 自动恢复。"""
    captured: dict = {}

    class _FakeTtsModel:
        sample_rate = 24000

    class _FakeVoxCPM:
        def __init__(self):
            self.tts_model = _FakeTtsModel()

        @classmethod
        def from_pretrained(cls, model_path, load_denoiser=False):
            captured["model_path"] = model_path
            captured["load_denoiser"] = load_denoiser
            return cls()

        def to(self, device):
            captured["device"] = device

        def generate(self, **kwargs):
            captured["generate_kwargs"] = kwargs
            # 0.1 秒 24kHz 静音
            return np.zeros(2400, dtype=np.float32)

    fake_module = ModuleType("voxcpm")
    fake_module.VoxCPM = _FakeVoxCPM
    monkeypatch.setitem(sys.modules, "voxcpm", fake_module)
    return captured


def test_load_passes_config_to_from_pretrained(mock_voxcpm):
    p = VoxCpmCloningProvider(
        name="vox", config={"model_dir": "/models/voxcpm", "load_denoiser": "true"},
    )
    p.load()
    assert p.loaded is True
    assert mock_voxcpm["model_path"] == "/models/voxcpm"
    assert mock_voxcpm["load_denoiser"] is True


def test_load_missing_model_dir_raises(mock_voxcpm):
    p = VoxCpmCloningProvider(name="vox", config={})
    with pytest.raises(ModelLoadError):
        p.load()


def test_load_without_voxcpm_package_raises(monkeypatch):
    # 隔离：模拟 voxcpm 未安装
    monkeypatch.setitem(sys.modules, "voxcpm", None)
    p = VoxCpmCloningProvider(name="vox", config={"model_dir": "/x"})
    with pytest.raises(ModelLoadError):
        p.load()


def test_synthesize_requires_reference_audio(mock_voxcpm):
    p = VoxCpmCloningProvider(name="vox", config={"model_dir": "/x"})
    p.load()
    with pytest.raises(InferenceError) as exc:
        p.synthesize("hello", voice_id="vx_xxx")
    assert "reference_audio_path is required" in exc.value.message


def test_synthesize_passes_kwargs_and_returns_wav(mock_voxcpm):
    p = VoxCpmCloningProvider(
        name="vox",
        config={
            "model_dir": "/x",
            "cfg_value": "1.5",
            "inference_timesteps": 8,
            "prompt_text": "你好世界",
        },
    )
    p.load()
    out = p.synthesize(
        "测试文本", voice_id="vx_xxx", reference_audio_path="/data/voices/vx_xxx.wav",
    )
    # 返回 WAV bytes（RIFF header）
    assert isinstance(out, bytes)
    assert out.startswith(b"RIFF")

    # 调用参数透传
    kw = mock_voxcpm["generate_kwargs"]
    assert kw["text"] == "测试文本"
    assert kw["prompt_wav_path"] == "/data/voices/vx_xxx.wav"
    assert kw["cfg_value"] == 1.5
    assert kw["inference_timesteps"] == 8
    assert kw["prompt_text"] == "你好世界"


def test_synthesize_skips_prompt_text_when_empty(mock_voxcpm):
    p = VoxCpmCloningProvider(name="vox", config={"model_dir": "/x"})
    p.load()
    p.synthesize("hi", voice_id="vx_x", reference_audio_path="/r.wav")
    assert "prompt_text" not in mock_voxcpm["generate_kwargs"]


def test_synthesize_unsupported_format_raises(mock_voxcpm):
    p = VoxCpmCloningProvider(name="vox", config={"model_dir": "/x"})
    p.load()
    with pytest.raises(InferenceError):
        p.synthesize("hi", voice_id="vx_x", format="mp3", reference_audio_path="/r.wav")


def test_clone_voice_returns_vx_id(mock_voxcpm):
    p = VoxCpmCloningProvider(name="vox", config={"model_dir": "/x"})
    p.load()
    vid = p.clone_voice("/r.wav", speaker_name="alice")
    assert vid.startswith("vx_")
    assert len(vid) == 3 + 12


def test_unload_resets_state(mock_voxcpm):
    p = VoxCpmCloningProvider(name="vox", config={"model_dir": "/x"})
    p.load()
    assert p.loaded
    p.unload()
    assert p.loaded is False
    assert p._model is None  # type: ignore[union-attr]
