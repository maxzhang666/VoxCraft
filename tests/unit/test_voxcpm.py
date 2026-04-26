"""VoxCpmCloningProvider 单元测试（mock voxcpm 包，不依赖真模型）。"""
from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace

import numpy as np
import pytest

from voxcraft.errors import InferenceError, ModelLoadError
from voxcraft.providers.cloning.voxcpm import VoxCpmCloningProvider


def _install_fake_voxcpm(monkeypatch, *, is_v2: bool) -> dict:
    """注入 mock voxcpm 模块。is_v2=True 时把内部 tts_model 类名设为 VoxCPM2Model
    并让 voxcpm.model.voxcpm2.VoxCPM2Model 可被 import；以匹配 provider 的 dispatch 检测。"""
    captured: dict = {}

    if is_v2:
        class VoxCPM2Model:  # noqa: N801 — 名字必须是 VoxCPM2Model 才能匹配 dispatch
            sample_rate = 24000

        tts_cls = VoxCPM2Model
    else:
        class _FakeTtsModel:
            sample_rate = 24000

        tts_cls = _FakeTtsModel

    class _FakeVoxCPM:
        def __init__(self):
            self.tts_model = tts_cls()

        @classmethod
        def from_pretrained(cls, model_path, load_denoiser=False):
            captured["model_path"] = model_path
            captured["load_denoiser"] = load_denoiser
            return cls()

        def to(self, device):
            captured["device"] = device

        def generate(self, **kwargs):
            captured["generate_kwargs"] = kwargs
            return np.zeros(2400, dtype=np.float32)

    fake_module = ModuleType("voxcpm")
    fake_module.VoxCPM = _FakeVoxCPM
    monkeypatch.setitem(sys.modules, "voxcpm", fake_module)

    if is_v2:
        # 让 `from voxcpm.model.voxcpm2 import VoxCPM2Model` 能解析到上面定义的类
        fake_model = ModuleType("voxcpm.model")
        fake_v2 = ModuleType("voxcpm.model.voxcpm2")
        fake_v2.VoxCPM2Model = tts_cls
        monkeypatch.setitem(sys.modules, "voxcpm.model", fake_model)
        monkeypatch.setitem(sys.modules, "voxcpm.model.voxcpm2", fake_v2)

    return captured


@pytest.fixture
def mock_voxcpm(monkeypatch):
    """默认 v1 mock（如 VoxCPM-0.5B）。测试结束 monkeypatch 自动恢复。"""
    return _install_fake_voxcpm(monkeypatch, is_v2=False)


@pytest.fixture
def mock_voxcpm_v2(monkeypatch):
    """v2 mock（如 VoxCPM2 / openbmb/VoxCPM2）。"""
    return _install_fake_voxcpm(monkeypatch, is_v2=True)


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


def test_synthesize_v1_without_prompt_text_raises(mock_voxcpm):
    """VoxCPM 1.x（0.5B）的克隆路径要求 prompt_wav_path + prompt_text 同传；
    缺转写文字时 voxcpm 自身会抛配对错误，provider 在调用前就显式拦截给清晰提示。"""
    p = VoxCpmCloningProvider(name="vox", config={"model_dir": "/x"})
    p.load()
    with pytest.raises(InferenceError) as exc:
        p.synthesize("hi", voice_id="vx_x", reference_audio_path="/r.wav")
    assert "transcript" in exc.value.message.lower()


def test_synthesize_v2_basic_clone_uses_reference_wav_path(mock_voxcpm_v2):
    """v2 + 无 prompt_text → 走 reference_wav_path 基础克隆。"""
    p = VoxCpmCloningProvider(name="vox", config={"model_dir": "/x"})
    p.load()
    p.synthesize("hi", voice_id="vx_x", reference_audio_path="/r.wav")
    kw = mock_voxcpm_v2["generate_kwargs"]
    assert kw["reference_wav_path"] == "/r.wav"
    assert "prompt_wav_path" not in kw
    assert "prompt_text" not in kw


def test_synthesize_v2_with_prompt_text_does_ultimate_cloning(mock_voxcpm_v2):
    """v2 + prompt_text → 三参数同传走 ultimate cloning。"""
    p = VoxCpmCloningProvider(
        name="vox",
        config={"model_dir": "/x", "prompt_text": "参考音频里讲的话"},
    )
    p.load()
    p.synthesize("hi", voice_id="vx_x", reference_audio_path="/r.wav")
    kw = mock_voxcpm_v2["generate_kwargs"]
    assert kw["prompt_wav_path"] == "/r.wav"
    assert kw["prompt_text"] == "参考音频里讲的话"
    assert kw["reference_wav_path"] == "/r.wav"


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
