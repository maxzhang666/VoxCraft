"""Moonshine v2（moonshine-ai/moonshine-v2）ASR Provider，走 batch API。

为什么是 v2（moonshine-voice）：
- v1（useful-moonshine-onnx）只英文，已废弃。我第一次集成踩坑：英文模型遇中文
  音频会 COVID-19 loop 幻觉
- v2 支持 8 个语种：英 / 中 / 日 / 韩 / 西 / 越 / 乌 / 阿（语种码二字母：
  en/zh/ja/ko/es/vi/uk/ar）

API（本地探出来的真实形态，不是搜索 / 文档 / 我猜的）：
    from moonshine_voice import (
        Transcriber, get_model_for_language, load_wav_file,
    )
    model_path, model_arch = get_model_for_language("zh")
    transcriber = Transcriber(
        model_path=model_path, model_arch=model_arch,
        update_interval=0.5, options=None,
    )
    audio_data, sample_rate = load_wav_file(wav_path)  # list[float], 16000
    transcript = transcriber.transcribe_without_streaming(
        audio_data, sample_rate=sample_rate,
    )
    # transcript.lines: List[TranscriptLine]
    # 每个 line: text / start_time / duration / words (List[WordTiming])
    # WordTiming: word / start / end / confidence

亮点：
- **有 segment 级时间戳**（TranscriptLine.start_time / duration）
- **有 word 级时间戳**（WordTiming.start/end/confidence）—— 比 Whisper-tiny 还细
- batch API 一行返回 Transcript，不用搞流式 listener

模型下载：moonshine-voice 库自管，按 language 调 `get_model_for_language`
从 HF 拉模型到 HF_HOME（容器内建议 `HF_HOME=/data/hf-home` 持久化）。语种切换
= 拉新模型；不进 VoxCraft 模型库 catalog。

CN 用户：设 `HF_ENDPOINT=https://hf-mirror.com` 走国内镜像。

Config 字段：
- language: enum  ar / es / en / ja / ko / vi / uk / zh（库 supported_languages()
                   返回的官方列表）
- device:   info-only enum（auto/cpu/cuda）；onnxruntime 自动按已装 EP 选
- update_interval: float  Transcriber 创建时的事件间隔；batch 路径其实用不到，
                          留着方便未来切流式
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import structlog

from voxcraft.errors import InferenceError, ModelLoadError
from voxcraft.providers.base import (
    AsrProvider,
    AsrResult,
    AsrSegment,
    ConfigField,
    ProviderInfo,
)


log = structlog.get_logger()


# moonshine_voice.supported_languages() 当前返回的官方列表
_LANG_OPTIONS = ("ar", "es", "en", "ja", "ko", "vi", "uk", "zh")


def _audio_duration_seconds(path: str) -> float:
    """读音频时长。先 soundfile（WAV/FLAC 快），失败 fallback ffprobe。"""
    try:
        import soundfile as sf  # noqa: PLC0415
        info = sf.info(path)
        if info.samplerate:
            return float(info.frames) / float(info.samplerate)
    except Exception:  # noqa: BLE001
        pass
    try:
        from voxcraft.video.ffmpeg_io import probe  # noqa: PLC0415
        info = probe(path)
        if info.duration:
            return float(info.duration)
    except Exception:  # noqa: BLE001
        pass
    return 0.0


def _ensure_wav(audio_path: str) -> tuple[str, bool]:
    """保证输入是 WAV。非 WAV → ffmpeg 抽到 16kHz mono 临时 WAV。

    返回 (path, owns_temp)；owns_temp=True 时调用方负责清理。
    """
    p = Path(audio_path)
    try:
        with open(p, "rb") as f:
            head = f.read(12)
        if len(head) >= 12 and head[:4] == b"RIFF" and head[8:12] == b"WAVE":
            return audio_path, False
    except OSError:
        pass

    from voxcraft.video.ffmpeg_io import extract_audio  # noqa: PLC0415
    tmp = Path(tempfile.mkstemp(suffix=".wav", prefix="moonshine_")[1])
    try:
        extract_audio(p, tmp)
    except Exception as e:  # noqa: BLE001
        tmp.unlink(missing_ok=True)
        raise InferenceError(
            f"Failed to convert input to WAV via ffmpeg: {e}",
            details={"source": str(p)},
        ) from e
    return str(tmp), True


class MoonshineProvider(AsrProvider):
    LABEL = "Moonshine v2（多语种边缘 ASR）"
    CONFIG_SCHEMA = [
        ConfigField(
            "language", "语种", "enum",
            options=_LANG_OPTIONS,
            default="en",
            required=True,
            help="决定加载哪个语种特化模型。zh = 中文，ja = 日文，ko = 韩文 ……"
            "首次切换语种会触发该语种模型从 HF 下载到 HF_HOME",
        ),
        ConfigField(
            "device", "设备（信息性）", "enum",
            options=("auto", "cpu", "cuda"), default="auto",
            help="onnxruntime 自动按已装 EP 选；本字段仅在 info() 展示，不做强制",
        ),
        ConfigField(
            "update_interval", "事件间隔（秒）", "str", default="0.5",
            help="流式 Transcriber 内部事件间隔；当前实现走 batch API，不影响结果",
        ),
    ]

    def __init__(self, name: str, config: dict) -> None:
        super().__init__(name, config)
        self._transcriber = None
        self._language: str | None = None
        self._model_arch_str: str | None = None

    def load(self) -> None:
        if self._loaded and self._transcriber is not None:
            return
        try:
            from moonshine_voice import (  # noqa: PLC0415
                Transcriber,
                get_model_for_language,
                model_arch_to_string,
            )
        except ImportError as e:
            raise ModelLoadError(
                "moonshine_voice 未安装。请检查 pyproject.toml 是否包含 "
                "moonshine-voice 依赖。",
                details={"provider": self.name, "import_error": str(e)},
            ) from e

        lang = (self.config.get("language") or "en").strip()
        try:
            update_interval = float(self.config.get("update_interval") or 0.5)
        except (TypeError, ValueError):
            update_interval = 0.5

        try:
            model_path, model_arch = get_model_for_language(lang)
        except Exception as e:  # noqa: BLE001
            raise ModelLoadError(
                f"Failed to fetch Moonshine v2 model for language={lang!r}: {e}. "
                f"支持的 language：{list(_LANG_OPTIONS)}。"
                "网络问题的话设 HF_ENDPOINT=https://hf-mirror.com",
                details={"provider": self.name, "language": lang},
            ) from e

        try:
            self._transcriber = Transcriber(
                model_path=model_path,
                model_arch=model_arch,
                update_interval=update_interval,
            )
        except Exception as e:  # noqa: BLE001
            raise ModelLoadError(
                f"Failed to instantiate Moonshine Transcriber: {e}",
                details={"provider": self.name, "model_path": str(model_path)},
            ) from e

        self._language = lang
        try:
            self._model_arch_str = model_arch_to_string(model_arch)
        except Exception:  # noqa: BLE001
            self._model_arch_str = str(model_arch)
        self._loaded = True
        log.info(
            "moonshine.load.done",
            provider=self.name, language=lang,
            model_path=str(model_path), model_arch=self._model_arch_str,
        )

    def unload(self) -> None:
        if self._transcriber is not None:
            close = getattr(self._transcriber, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:  # noqa: BLE001
                    pass
        self._transcriber = None
        self._language = None
        self._model_arch_str = None
        self._loaded = False

    def info(self) -> ProviderInfo:
        try:
            import onnxruntime as ort  # noqa: PLC0415
            providers = ort.get_available_providers()
        except ImportError:
            providers = []
        return ProviderInfo(
            kind="asr",
            name=self.name,
            class_name=type(self).__name__,
            loaded=self._loaded,
            extra={
                "language": self._language or self.config.get("language", "en"),
                "model_arch": self._model_arch_str,
                "device": self.config.get("device", "auto"),
                "ort_providers": providers,
            },
        )

    def transcribe(
        self,
        audio_path: str,
        language: str | None = None,  # noqa: ARG002 — v2 按 load 时绑定的 language
        progress_cb=None,
        options: dict | None = None,  # noqa: ARG002 — v2 batch 没有请求级调参
    ) -> AsrResult:
        if not self._loaded or self._transcriber is None:
            raise InferenceError(
                "MoonshineProvider not loaded; call load() first",
                details={"provider": self.name},
            )

        # 1. 保证 WAV（非 WAV 走 ffmpeg 抽 16kHz mono）
        wav_path, owns_tmp = _ensure_wav(audio_path)

        try:
            from moonshine_voice import load_wav_file  # noqa: PLC0415
        except ImportError as e:
            if owns_tmp:
                Path(wav_path).unlink(missing_ok=True)
            raise InferenceError(
                "moonshine_voice import failed at transcribe time",
                details={"provider": self.name, "error": str(e)},
            ) from e

        # 2. 读音频成 PCM float list
        try:
            audio_data, sample_rate = load_wav_file(wav_path)
        except Exception as e:  # noqa: BLE001
            if owns_tmp:
                Path(wav_path).unlink(missing_ok=True)
            raise InferenceError(
                f"Failed to load WAV via moonshine_voice.load_wav_file: {e}",
                details={"provider": self.name, "audio": audio_path},
            ) from e

        # 3. batch 转录
        try:
            transcript = self._transcriber.transcribe_without_streaming(
                audio_data, sample_rate=sample_rate,
            )
        except Exception as e:  # noqa: BLE001
            if owns_tmp:
                Path(wav_path).unlink(missing_ok=True)
            raise InferenceError(
                f"Moonshine transcription failed: {e}",
                details={"provider": self.name, "audio": audio_path},
            ) from e

        # 4. 转换成 AsrResult。Moonshine v2 给的颗粒度：
        #    - line.text / start_time / duration   →  AsrSegment
        #    - line.words[] (WordTiming: word/start/end/confidence)  →  segment.words
        segments: list[AsrSegment] = []
        lines = getattr(transcript, "lines", None) or []
        for line in lines:
            text = (getattr(line, "text", "") or "").strip()
            if not text:
                continue
            start = float(getattr(line, "start_time", 0.0) or 0.0)
            dur = float(getattr(line, "duration", 0.0) or 0.0)
            seg = AsrSegment(start=start, end=start + dur, text=text)
            words = getattr(line, "words", None) or []
            if words:
                seg.words = [  # type: ignore[attr-defined]
                    {
                        "start": float(w.start),
                        "end": float(w.end),
                        "word": w.word,
                        "probability": float(w.confidence),
                    }
                    for w in words
                ]
            segments.append(seg)

        if owns_tmp:
            Path(wav_path).unlink(missing_ok=True)

        if progress_cb is not None:
            try:
                progress_cb(1.0)
            except Exception:  # noqa: BLE001
                pass

        duration = _audio_duration_seconds(audio_path)
        # 如果 lines 全空，构造一个空 segment 满足 AsrResult 契约（避免下游 crash）
        if not segments:
            log.warning(
                "moonshine.transcribe.empty",
                provider=self.name, audio=audio_path,
            )
            segments = [AsrSegment(start=0.0, end=duration, text="")]

        return AsrResult(
            segments=segments,
            language=self._language or "en",
            duration=duration,
        )
