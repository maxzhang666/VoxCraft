"""Provider 注册表（显式映射，KISS）。

新增 Provider 实现：在本文件添加一条 import + 字典条目。
Mock Provider 不登记（测试通过 monkeypatch 注入，见 providers.md）。
"""
from __future__ import annotations

from voxcraft.errors import ProviderError
from voxcraft.providers.asr.whisper import WhisperProvider
from voxcraft.providers.base import Provider
from voxcraft.providers.cloning.indextts import IndexTtsProvider
from voxcraft.providers.cloning.voxcpm import VoxCpmCloningProvider
from voxcraft.providers.separator.demucs import DemucsProvider
from voxcraft.providers.tts.piper import PiperProvider


PROVIDER_REGISTRY: dict[str, type[Provider]] = {
    "WhisperProvider": WhisperProvider,
    "PiperProvider": PiperProvider,
    "VoxCpmCloningProvider": VoxCpmCloningProvider,
    "IndexTtsProvider": IndexTtsProvider,
    "DemucsProvider": DemucsProvider,
    # OpenAiCompatProvider（翻译，v0.5+）
}


def resolve(class_name: str) -> type[Provider]:
    try:
        return PROVIDER_REGISTRY[class_name]
    except KeyError:
        raise ProviderError(
            f"Unknown provider class: {class_name}",
            code="PROVIDER_UNKNOWN",
            status_code=400,
        )


def instantiate(class_name: str, name: str, config: dict) -> Provider:
    cls = resolve(class_name)
    return cls(name=name, config=config)
