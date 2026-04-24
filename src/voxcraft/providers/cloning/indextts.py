"""IndexTTS 声纹克隆骨架（B 站，非商业许可）。

⚠️ License：IndexTTS 非商业许可（CPML 类）。自托管场景合规，勿商用。
详见 ADR-002。

MVP 未在开发机集成。部署到 GPU 主机时参考：
    https://github.com/index-tts/index-tts

Config：
- model_dir: str
- device: str
"""
from __future__ import annotations

from voxcraft.errors import InferenceError, ModelLoadError
from voxcraft.providers import capabilities
from voxcraft.providers.base import CloningProvider, ConfigField, ProviderInfo, Voice


class IndexTtsProvider(CloningProvider):
    LABEL = "IndexTTS（B 站，非商业）"
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
            import indextts  # type: ignore[import-not-found]
        except ImportError as e:
            raise ModelLoadError(
                "indextts not installed; install on deployment host",
                details={"provider": self.name},
            ) from e
        try:
            self._model = indextts.load(  # type: ignore[attr-defined]
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
                f"Failed to load IndexTTS: {e}",
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
            extra={"non_commercial": True},
        )

    def synthesize(
        self,
        text: str,
        voice_id: str,
        speed: float = 1.0,
        format: str = "wav",
    ) -> bytes:
        if self._model is None:
            raise InferenceError("IndexTTS not loaded")
        raise NotImplementedError("IndexTTS synthesize: 待真机部署阶段接入")

    def list_voices(self) -> list[Voice]:
        return []

    def clone_voice(
        self, reference_audio_path: str, speaker_name: str | None = None,
    ) -> str:
        if self._model is None:
            raise InferenceError("IndexTTS not loaded")
        raise NotImplementedError("IndexTTS clone_voice: 待真机部署阶段接入")
