"""Piper TTS（ONNX runtime 后端）。

Config：
- model: str      ONNX 模型路径（如 /models/piper/zh_CN-huayan-medium.onnx）
- volume: float   可选，默认 1.0

注意：Piper 只输出 WAV；API `format` 参数为 mp3/ogg 时仍返回 wav，
转码延迟到 v0.2 接入 ffmpeg 处理。
"""
from __future__ import annotations

import io
import wave

from voxcraft.errors import InferenceError, ModelLoadError
from voxcraft.providers.base import ConfigField, ProviderInfo, TtsProvider, Voice


class PiperProvider(TtsProvider):
    LABEL = "Piper（ONNX 本地合成）"
    CONFIG_SCHEMA = [
        ConfigField(
            "model", "模型路径", "path", required=True,
            help="ONNX 模型文件路径，如 /models/piper/zh_CN-huayan-medium.onnx",
        ),
        ConfigField(
            "volume", "音量", "str", default="1.0",
            help="可选，浮点数；默认 1.0",
        ),
    ]

    def __init__(self, name: str, config: dict) -> None:
        super().__init__(name, config)
        self._voice = None

    def load(self) -> None:
        if self._loaded and self._voice is not None:
            return
        try:
            from piper import PiperVoice
        except ImportError as e:
            raise ModelLoadError(
                "piper-tts not installed",
                details={"provider": self.name},
            ) from e
        try:
            self._voice = PiperVoice.load(self.config["model"])
            self._loaded = True
        except KeyError as e:
            raise ModelLoadError(
                f"Missing config field: {e.args[0]}",
                details={"provider": self.name},
            ) from e
        except Exception as e:
            raise ModelLoadError(
                f"Failed to load piper voice: {e}",
                details={"provider": self.name, "config": self.config},
            ) from e

    def unload(self) -> None:
        self._voice = None
        self._loaded = False

    def info(self) -> ProviderInfo:
        return ProviderInfo(
            kind="tts",
            name=self.name,
            class_name=type(self).__name__,
            loaded=self._loaded,
        )

    def synthesize(
        self,
        text: str,
        voice_id: str,
        speed: float = 1.0,
        format: str = "wav",
        reference_audio_path: str | None = None,  # noqa: ARG002 — Piper 是预设音色，参考音频无意义
    ) -> bytes:
        if self._voice is None:
            raise InferenceError(
                "PiperProvider not loaded", details={"provider": self.name}
            )
        try:
            from piper.config import SynthesisConfig

            syn = SynthesisConfig(
                length_scale=1.0 / max(0.5, min(2.0, speed)),
                volume=float(self.config.get("volume", 1.0)),
            )
            buf = io.BytesIO()
            wav = wave.open(buf, "wb")
            try:
                self._voice.synthesize_wav(
                    text, wav, syn_config=syn, set_wav_format=True
                )
            finally:
                wav.close()
            return buf.getvalue()
        except Exception as e:
            raise InferenceError(
                f"Piper synthesis failed: {e}",
                details={"provider": self.name},
            ) from e

    def list_voices(self) -> list[Voice]:
        # Piper 单模型单音色；以 Provider name 作 voice_id
        return [Voice(id=self.name, language="zh")]
