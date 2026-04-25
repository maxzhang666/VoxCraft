"""faster-whisper 实现的 AsrProvider。

Config 字段（全部可选，除 model_path 外）：
- model_path: str               本地目录 或 HF repo id，如 "Systran/faster-whisper-medium"
- compute_type: str             默认 "int8"
- device: str                   默认 "auto"
- simplify_chinese: enum        "true"/"false"；默认 "true"；中文识别结果自动转简体
- beam_size: int                默认 5；解码 beam 宽度，调大→更准更慢
- initial_prompt: str           默认空；领域词汇/风格提示，能改善专业术语识别
- temperature: float            默认 0.0；0=贪婪可复现，>0 引入采样
- condition_on_previous_text:   默认 "true"；长音频幻觉传播时关闭
- compression_ratio_threshold:  默认 2.4；压缩比超过则视为劣质段
- log_prob_threshold:           默认 -1.0；logprob 低于则视为劣质段
- no_speech_threshold:          默认 0.6；无语音概率高于则判为静音
- vad_filter: enum              "true"/"false"；默认 "false"；开启 Silero VAD
- word_timestamps: enum         "true"/"false"；默认 "false"；输出词级时间戳

API 请求级覆盖：transcribe(audio_path, language, options=...) 中 options 同名 key
覆盖 Provider config，实现"管理员配默认 / 调用方按需调整"分层。
"""
from __future__ import annotations

from typing import Any

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


def _as_bool(v: Any, default: bool) -> bool:
    """统一字符串/布尔转 bool。Form 传过来通常是 "true"/"false"，config 也是字符串。"""
    if v is None:
        return default
    if isinstance(v, bool):
        return v
    s = str(v).strip().lower()
    if s in ("true", "1", "yes", "on"):
        return True
    if s in ("false", "0", "no", "off", ""):
        return False
    return default


def _as_float(v: Any, default: float) -> float:
    if v is None or v == "":
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _as_int(v: Any, default: int) -> int:
    if v is None or v == "":
        return default
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _as_str(v: Any, default: str = "") -> str:
    if v is None:
        return default
    return str(v)


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
        # ---- 解码精度调优 ----
        ConfigField(
            "beam_size", "Beam 宽度", "int", default=5,
            help="解码 beam search 宽度；增大→更准但更慢，常用 1（贪婪）~10",
        ),
        ConfigField(
            "initial_prompt", "初始 Prompt（领域词汇）", "str", default="",
            help="如\"以下是普通话演讲。\"或专业术语列表，能改善专有名词识别",
        ),
        ConfigField(
            "temperature", "温度", "str", default="0.0",
            help="0 = 贪婪解码（可复现）；>0 引入采样随机性。faster-whisper 库默认 fallback 列表此处单值化",
        ),
        ConfigField(
            "condition_on_previous_text", "上下文延续", "enum",
            options=("true", "false"), default="true",
            help="长音频出现重复幻觉时建议关闭，避免错误传播",
        ),
        ConfigField(
            "vad_filter", "VAD 过滤静音", "enum",
            options=("true", "false"), default="false",
            help="启用 Silero VAD 跳过静音/非语音段，含背景噪声音频强烈推荐",
        ),
        ConfigField(
            "word_timestamps", "输出词级时间戳", "enum",
            options=("true", "false"), default="false",
            help="开启后 segments 含 words 信息；视频翻译对齐用，但慢约 30%",
        ),
        ConfigField(
            "compression_ratio_threshold", "压缩比阈值", "str", default="2.4",
            help="超过此值视为劣质段，触发 fallback；调低（如 1.8）更激进过滤幻觉",
        ),
        ConfigField(
            "log_prob_threshold", "Logprob 阈值", "str", default="-1.0",
            help="平均 logprob 低于此值视为劣质段；调高（-0.5）更严格",
        ),
        ConfigField(
            "no_speech_threshold", "无语音阈值", "str", default="0.6",
            help="无语音概率高于此判为静音；调高更易判静音",
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

    def _build_transcribe_kwargs(self, options: dict | None) -> dict[str, Any]:
        """合并 Provider config 默认值与请求级 options，得到 model.transcribe 的 kwargs。

        优先级：options[k] > config[k] > faster-whisper 库默认。
        空字符串视为未指定（让用户在 UI 清空字段意为"用默认"）。
        """
        opts = options or {}
        cfg = self.config

        def pick(key: str) -> Any:
            v = opts.get(key)
            if v is not None and v != "":
                return v
            return cfg.get(key)

        kwargs: dict[str, Any] = {
            "beam_size": _as_int(pick("beam_size"), 5),
            "temperature": _as_float(pick("temperature"), 0.0),
            "condition_on_previous_text": _as_bool(
                pick("condition_on_previous_text"), True
            ),
            "compression_ratio_threshold": _as_float(
                pick("compression_ratio_threshold"), 2.4
            ),
            "log_prob_threshold": _as_float(pick("log_prob_threshold"), -1.0),
            "no_speech_threshold": _as_float(pick("no_speech_threshold"), 0.6),
            "vad_filter": _as_bool(pick("vad_filter"), False),
            "word_timestamps": _as_bool(pick("word_timestamps"), False),
        }
        prompt = _as_str(pick("initial_prompt"), "")
        if prompt:
            kwargs["initial_prompt"] = prompt
        return kwargs

    def transcribe(
        self,
        audio_path: str,
        language: str | None = None,
        progress_cb=None,
        options: dict | None = None,
    ) -> AsrResult:
        if self._model is None:
            raise InferenceError(
                "WhisperProvider not loaded; call load() first",
                details={"provider": self.name},
            )
        try:
            kwargs = self._build_transcribe_kwargs(options)
            segments_iter, whisper_info = self._model.transcribe(
                audio_path, language=language, **kwargs
            )
            duration = whisper_info.duration or 0.0
            simplify = (
                (whisper_info.language or "").lower() == "zh"
                and str(self.config.get("simplify_chinese", "true")).lower() == "true"
            )
            include_words = kwargs.get("word_timestamps", False)
            segments: list[AsrSegment] = []
            # faster-whisper 的 segments 是 generator——逐个汇报进度
            for s in segments_iter:
                text = _to_simplified(s.text) if simplify else s.text
                seg = AsrSegment(start=s.start, end=s.end, text=text)
                if include_words and getattr(s, "words", None):
                    # 词级时间戳（如 word_timestamps=True）通过 extra 透传，不破坏现有 schema
                    words_payload = [
                        {
                            "start": w.start,
                            "end": w.end,
                            "word": _to_simplified(w.word) if simplify else w.word,
                            "probability": getattr(w, "probability", None),
                        }
                        for w in s.words
                    ]
                    setattr(seg, "words", words_payload)  # noqa: B010 — 运行时附加
                segments.append(seg)
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
