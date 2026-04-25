"""骨架 Provider：构造不加载；load() 因依赖缺失抛 ModelLoadError。

部署到 GPU 主机后装上依赖再补 E2E 测试。
Piper 已真实实装（见 test_piper.py），不在本文件。
"""
from __future__ import annotations

import pytest

from voxcraft.errors import ModelLoadError
from voxcraft.providers.cloning.indextts import IndexTtsProvider
from voxcraft.providers.cloning.voxcpm import VoxCpmCloningProvider
from voxcraft.providers.separator.demucs import DemucsProvider


@pytest.mark.parametrize(
    "cls,config",
    [
        (VoxCpmCloningProvider, {"model_dir": "/x"}),
        (IndexTtsProvider, {"model_dir": "/x"}),
        (DemucsProvider, {"model_name": "htdemucs"}),
    ],
)
def test_stub_construction_no_side_effect(cls, config):
    p = cls(name="t", config=config)
    assert p.loaded is False
    info = p.info()
    assert info.class_name == cls.__name__


@pytest.mark.parametrize(
    "cls,config",
    [
        (VoxCpmCloningProvider, {"model_dir": "/x"}),
        (IndexTtsProvider, {"model_dir": "/x"}),
        (DemucsProvider, {"model_name": "htdemucs"}),
    ],
)
def test_stub_load_raises_model_load_error_without_deps(cls, config):
    p = cls(name="t", config=config)
    with pytest.raises(ModelLoadError) as exc:
        p.load()
    assert exc.value.code == "MODEL_LOAD_ERROR"
    msg = exc.value.message.lower()
    # 两种合理失败：依赖未装 / 依赖装了但 model_dir 路径无效
    assert (
        "not installed" in msg
        or "not found" in msg
        or "failed" in msg
        or "missing" in msg
    )
