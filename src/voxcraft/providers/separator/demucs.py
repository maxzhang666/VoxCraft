"""Demucs 人声分离骨架（Meta，MIT）。

MVP 未在开发机集成。部署到 GPU 主机时：
    pip install demucs

Config：
- model_name: str   "htdemucs" / "mdx_extra_q" 等
- device: str       "cpu" / "cuda:0"
"""
from __future__ import annotations

from voxcraft.errors import InferenceError, ModelLoadError
from voxcraft.providers.base import (
    ConfigField,
    ProviderInfo,
    SeparateResult,
    SeparatorProvider,
)


class DemucsProvider(SeparatorProvider):
    LABEL = "Demucs（Meta 人声分离）"
    CONFIG_SCHEMA = [
        ConfigField(
            "model_name", "模型", "enum",
            options=("htdemucs", "htdemucs_ft", "mdx_extra_q"),
            default="htdemucs",
            help="预训练权重名",
        ),
        ConfigField(
            "device", "设备", "enum",
            options=("auto", "cpu", "cuda"), default="auto",
        ),
    ]

    def __init__(self, name: str, config: dict) -> None:
        super().__init__(name, config)
        self._model = None

    def load(self) -> None:
        if self._loaded:
            return
        try:
            from demucs.pretrained import get_model  # type: ignore[import-not-found]
        except ImportError as e:
            raise ModelLoadError(
                "demucs not installed; run `pip install demucs` on deployment host",
                details={"provider": self.name},
            ) from e
        try:
            self._model = get_model(self.config.get("model_name", "htdemucs"))
            self._loaded = True
        except Exception as e:
            raise ModelLoadError(
                f"Failed to load demucs model: {e}",
                details={"provider": self.name},
            ) from e

    def unload(self) -> None:
        self._model = None
        self._loaded = False

    def info(self) -> ProviderInfo:
        return ProviderInfo(
            kind="separator",
            name=self.name,
            class_name=type(self).__name__,
            loaded=self._loaded,
            extra={"model": self.config.get("model_name", "htdemucs")},
        )

    def separate(self, audio_path: str) -> SeparateResult:
        if self._model is None:
            raise InferenceError("DemucsProvider not loaded")
        raise NotImplementedError("Demucs separate: 待真机部署阶段接入")
