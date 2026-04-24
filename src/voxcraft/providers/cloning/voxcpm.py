"""VoxCPM 声纹克隆骨架（Apache 2.0，商业友好）。

MVP 未在开发机集成。部署到 GPU 主机时参考：
    https://github.com/OpenBMB/VoxCPM

Config：
- model_dir: str  本地目录或 HF repo id
- device: str     "cpu" / "cuda:0" / "auto"
"""
from __future__ import annotations

from voxcraft.errors import InferenceError, ModelLoadError
from voxcraft.providers import capabilities
from voxcraft.providers.base import CloningProvider, ConfigField, ProviderInfo, Voice


class VoxCpmCloningProvider(CloningProvider):
    LABEL = "VoxCPM（开源声纹克隆）"
    CAPABILITIES = frozenset({capabilities.CLONE})
    CONFIG_SCHEMA = [
        ConfigField(
            "model_dir", "模型目录", "path", required=True,
            help="本地目录或 HF repo id",
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
            import voxcpm  # type: ignore[import-not-found]
        except ImportError as e:
            raise ModelLoadError(
                "voxcpm not installed; install on deployment host per OpenBMB/VoxCPM README",
                details={"provider": self.name},
            ) from e
        try:
            self._model = voxcpm.load_model(  # type: ignore[attr-defined]
                self.config["model_dir"],
                device=self.config.get("device", "cpu"),
            )
            self._loaded = True
        except KeyError as e:
            raise ModelLoadError(
                f"Missing config field: {e.args[0]}",
                details={"provider": self.name},
            ) from e
        except Exception as e:
            raise ModelLoadError(
                f"Failed to load VoxCPM: {e}",
                details={"provider": self.name},
            ) from e

    def unload(self) -> None:
        self._model = None
        self._loaded = False

    def info(self) -> ProviderInfo:
        return ProviderInfo(
            kind="cloning",
            name=self.name,
            class_name=type(self).__name__,
            loaded=self._loaded,
            extra={"device": self.config.get("device", "cpu")},
        )

    def synthesize(
        self,
        text: str,
        voice_id: str,
        speed: float = 1.0,
        format: str = "wav",
    ) -> bytes:
        if self._model is None:
            raise InferenceError("VoxCPM not loaded")
        # 真实调用：self._model.synthesize(text, voice_ref=..., speed=speed)
        raise NotImplementedError("VoxCPM synthesize: 待真机部署阶段接入")

    def list_voices(self) -> list[Voice]:
        return []

    def clone_voice(
        self, reference_audio_path: str, speaker_name: str | None = None,
    ) -> str:
        if self._model is None:
            raise InferenceError("VoxCPM not loaded")
        raise NotImplementedError("VoxCPM clone_voice: 待真机部署阶段接入")
