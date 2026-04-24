"""faster-whisper 实现的 AsrProvider。

Config 字段（全部可选，除 model_path 外）：
- model_path: str         本地目录 或 HF repo id，如 "Systran/faster-whisper-medium"
- compute_type: str       默认 "int8"
- device: str             默认 "cpu"（"cuda"/"auto" 可用）
- simplify_chinese: str   "true"/"false"；默认 "true"；中文识别结果自动转简体
                          （Whisper 训练语料以繁体居多，language=zh 也不保证简体）
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


def _to_simplified(text: str) -> str:
    """用 zhconv 把繁体转简体；不含中文字符的 text 直接返回。"""
    if not text:
        return text
    # 快速过滤：无中文字符时跳过，避免无谓调用
    if not any("一" <= ch <= "鿿" for ch in text):
        return text
    try:
        import zhconv
        return zhconv.convert(text, "zh-cn")
    except Exception:  # noqa: BLE001
        return text  # 转换失败退化为原文，不影响主流程


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
        ConfigField(
            "simplify_chinese", "中文自动简体化", "enum",
            options=("true", "false"), default="true",
            help="Whisper 训练语料中文多为繁体；开启后对 language=zh 的结果做 zhconv 转换",
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
        self,
        audio_path: str,
        language: str | None = None,
        progress_cb=None,
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
            duration = whisper_info.duration or 0.0
            simplify = (
                (whisper_info.language or "").lower() == "zh"
                and str(self.config.get("simplify_chinese", "true")).lower() == "true"
            )
            segments: list[AsrSegment] = []
            # faster-whisper 的 segments 是 generator——逐个汇报进度
            for s in segments_iter:
                text = _to_simplified(s.text) if simplify else s.text
                segments.append(AsrSegment(start=s.start, end=s.end, text=text))
                if progress_cb is not None and duration > 0:
                    try:
                        progress_cb(min(1.0, s.end / duration))
                    except Exception:  # noqa: BLE001
                        pass  # 进度回调失败不影响转录
            if progress_cb is not None:
                try:
                    progress_cb(1.0)
                except Exception:  # noqa: BLE001
                    pass
            return AsrResult(
                segments=segments,
                language=whisper_info.language,
                duration=duration,
            )
        except Exception as e:
            raise InferenceError(
                f"Transcription failed: {e}",
                details={"provider": self.name, "audio": audio_path},
            ) from e
