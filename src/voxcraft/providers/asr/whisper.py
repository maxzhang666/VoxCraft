"""faster-whisper 实现的 AsrProvider。

Config 字段（全部可选，除 model_path 外）：
- model_path: str         本地目录 或 HF repo id，如 "Systran/faster-whisper-medium"
- compute_type: str       默认 "int8"
- device: str             默认 "cpu"（"cuda"/"auto" 可用）
"""
from __future__ import annotations

from voxcraft.errors import InferenceError, ModelLoadError
from voxcraft.providers.base import (
    AsrProvider,
    AsrResult,
    AsrSegment,
    ConfigField,
    ProviderInfo,
)


class WhisperProvider(AsrProvider):
    LABEL = "Whisper（faster-whisper）"
    CONFIG_SCHEMA = [
        ConfigField(
            "model_path", "模型路径", "path", required=True,
            help="本地目录或 HF repo id，如 Systran/faster-whisper-medium",
        ),
        ConfigField(
            "compute_type", "量化", "enum",
            options=("int8", "fp16", "fp32"), default="int8",
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
        if self._loaded and self._model is not None:
            return
        try:
            from faster_whisper import WhisperModel

            self._model = WhisperModel(
                self.config["model_path"],
                device=self.config.get("device", "cpu"),
                compute_type=self.config.get("compute_type", "int8"),
            )
            self._loaded = True
        except KeyError as e:
            raise ModelLoadError(
                f"Missing required config field: {e.args[0]}",
                details={"provider": self.name},
            ) from e
        except Exception as e:
            raise ModelLoadError(
                f"Failed to load whisper model: {e}",
                details={"provider": self.name, "config": self.config},
            ) from e

    def unload(self) -> None:
        self._model = None
        self._loaded = False

    def info(self) -> ProviderInfo:
        return ProviderInfo(
            kind="asr",
            name=self.name,
            class_name=type(self).__name__,
            loaded=self._loaded,
            extra={
                "compute_type": self.config.get("compute_type", "int8"),
                "device": self.config.get("device", "cpu"),
            },
        )

    def transcribe(
        self, audio_path: str, language: str | None = None
    ) -> AsrResult:
        if self._model is None:
            raise InferenceError(
                "WhisperProvider not loaded; call load() first",
                details={"provider": self.name},
            )
        try:
            segments_iter, whisper_info = self._model.transcribe(
                audio_path, language=language
            )
            segments = [
                AsrSegment(start=s.start, end=s.end, text=s.text)
                for s in segments_iter
            ]
            return AsrResult(
                segments=segments,
                language=whisper_info.language,
                duration=whisper_info.duration,
            )
        except Exception as e:
            raise InferenceError(
                f"Transcription failed: {e}",
                details={"provider": self.name, "audio": audio_path},
            ) from e
