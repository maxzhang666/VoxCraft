"""GPT-SoVITS v2Pro 声纹克隆（B 站 RVC-Boss，MIT 商业友好）。

API 来源：RVC-Boss/GPT-SoVITS commit ea2d2a8 — GPT_SoVITS/TTS_infer_pack/TTS.py
- TTS_Config(configs: Union[dict, str])：dict 形式时必须含 "custom" 或 vN section
- TTS(configs).run(inputs: dict) → generator[(sr, np.int16 array)]
- inputs 字段：text / text_lang / ref_audio_path / prompt_text / prompt_lang +
  采样参数 top_k/top_p/temperature/text_split_method/speed_factor 等

集成形态：
- 仓库由 Dockerfile git clone 到 /opt/GPT-SoVITS（PYTHONPATH 注入），不走 PyPI
- Provider 不依赖 yaml 配置文件，运行时直接构造 dict 传给 TTS_Config
- 跨语种克隆：text_lang="zh" + prompt_lang="en"/"ja"/"ko" 即可

注意：
- TTS_Config 内部 default_configs 路径相对于 cwd（"GPT_SoVITS/pretrained_models/..."）；
  当用户传的绝对路径有任一不存在时会回退到这些相对路径，找不到资源会硬崩。
  load() 切到 /opt/GPT-SoVITS 让 fallback 能解析（但优先确保用户路径都存在）。
- v2Pro 必填 prompt_text + prompt_lang（v3/v4 同；v2/v2 ref_free 模式质量差不暴露）。
  Provider 沿用 prompt_text 全局配置（与 voxcpm v1 模式一致），后续可改 voice 粒度。
"""
from __future__ import annotations

import io
import os
import uuid
import wave
from pathlib import Path

import structlog

from voxcraft.errors import InferenceError, ModelLoadError
from voxcraft.providers import capabilities
from voxcraft.providers.base import CloningProvider, ConfigField, ProviderInfo, Voice
from voxcraft.runtime.gpu import resolve_device, vram_usage_mb


log = structlog.get_logger()

# v2Pro 的标准目录布局（HF lj1995/GPT-SoVITS）
_V2PRO_LAYOUT = {
    "bert_base_path": "chinese-roberta-wwm-ext-large",
    "cnhuhbert_base_path": "chinese-hubert-base",
    "t2s_weights_path": "s1v3.ckpt",
    "vits_weights_path": "v2Pro/s2Gv2Pro.pth",
}
_V2PROPLUS_LAYOUT = {
    "bert_base_path": "chinese-roberta-wwm-ext-large",
    "cnhuhbert_base_path": "chinese-hubert-base",
    "t2s_weights_path": "s1v3.ckpt",
    "vits_weights_path": "v2Pro/s2Gv2ProPlus.pth",
}
# 简化：只暴露 v2Pro / v2ProPlus；v3/v4 的 BigVGAN 体量大且依赖 vocoder 子模型
_LAYOUTS: dict[str, dict[str, str]] = {
    "v2Pro": _V2PRO_LAYOUT,
    "v2ProPlus": _V2PROPLUS_LAYOUT,
}


def _dir_size_mb(path: str | None) -> int:
    if not path:
        return 0
    try:
        total = sum(f.stat().st_size for f in Path(path).rglob("*") if f.is_file())
        return int(total // (1024 * 1024))
    except OSError:
        return 0


def _i16_to_wav_bytes(audio, sample_rate: int) -> bytes:
    """把 int16 numpy 数组打包为 WAV bytes。"""
    import numpy as np

    arr = np.asarray(audio, dtype=np.int16)
    if arr.ndim > 1:
        arr = arr.reshape(-1)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(arr.tobytes())
    return buf.getvalue()


class GptSoVitsProvider(CloningProvider):
    LABEL = "GPT-SoVITS v2Pro（B 站，开源）"
    CAPABILITIES = frozenset({capabilities.CLONE})
    CONFIG_SCHEMA = [
        ConfigField(
            "model_dir", "模型目录", "path", required=True,
            help="本地目录，需包含 chinese-roberta-wwm-ext-large/ + chinese-hubert-base/ "
            "+ s1v3.ckpt + v2Pro/s2Gv2Pro.pth（HF lj1995/GPT-SoVITS）",
        ),
        ConfigField(
            "version", "版本", "enum",
            options=("v2Pro", "v2ProPlus"), default="v2Pro",
            help="v2ProPlus 模型大但保真度更高；8GB 显存可跑两者",
        ),
        ConfigField(
            "device", "设备", "enum",
            options=("auto", "cpu", "cuda"), default="auto",
        ),
        ConfigField(
            "is_half", "FP16 推理", "enum",
            options=("true", "false"), default="false",
            help="GPU 启用减半显存与加速；CPU 不支持",
        ),
        ConfigField(
            "prompt_text", "Prompt 文本", "str", default="",
            help="参考音频对应的转写文字（必填）；GPT-SoVITS v2Pro 强制要求",
        ),
        ConfigField(
            "prompt_lang", "Prompt 语言", "enum",
            options=("auto", "zh", "en", "ja", "ko", "yue"), default="auto",
            help="参考音频的语言；跨语种克隆请明确指定",
        ),
        ConfigField(
            "text_split_method", "切分方式", "enum",
            options=("cut0", "cut1", "cut2", "cut3", "cut4", "cut5"), default="cut5",
            help="cut0=不切；cut5=按标点切（长文本必选）",
        ),
        ConfigField(
            "top_k", "采样 top_k", "int", default=15,
        ),
        ConfigField(
            "top_p", "采样 top_p", "str", default="1.0",
        ),
        ConfigField(
            "temperature", "温度", "str", default="1.0",
        ),
    ]

    def __init__(self, name: str, config: dict) -> None:
        super().__init__(name, config)
        self._tts = None
        self._sample_rate: int = 32000  # v2Pro 默认；load 后从模型读取覆盖

    def _import_gpt_sovits(self):
        """在 import 前 chdir 到仓库根，让 GPT-SoVITS 内部相对路径（g2p 词典等）可解析。"""
        gpt_sovits_root = os.environ.get("GPT_SOVITS_ROOT", "/opt/GPT-SoVITS")
        if os.path.isdir(gpt_sovits_root):
            try:
                os.chdir(gpt_sovits_root)
            except OSError:
                pass
        try:
            from GPT_SoVITS.TTS_infer_pack.TTS import TTS, TTS_Config  # type: ignore[import-not-found]
        except ImportError as e:
            raise ModelLoadError(
                "GPT-SoVITS not installed; rebuild image (Dockerfile git clones to "
                "/opt/GPT-SoVITS + runtime PYTHONPATH 注入)",
                details={"provider": self.name},
            ) from e
        return TTS, TTS_Config

    def _build_paths(self, model_dir: str, version: str) -> dict[str, str]:
        layout = _LAYOUTS.get(version)
        if layout is None:
            raise ModelLoadError(
                f"Unsupported version: {version!r}; expected one of {list(_LAYOUTS)}",
                details={"provider": self.name},
            )
        paths = {k: str(Path(model_dir) / v) for k, v in layout.items()}
        missing = [k for k, p in paths.items() if not Path(p).exists()]
        if missing:
            raise ModelLoadError(
                f"GPT-SoVITS missing files: {missing}. 检查 model_dir 是否完整下载 "
                "lj1995/GPT-SoVITS（chinese-roberta-wwm-ext-large/ + chinese-hubert-base/ "
                "+ s1v3.ckpt + v2Pro/*.pth）",
                details={"provider": self.name, "model_dir": model_dir, "missing": missing},
            )
        return paths

    def load(self) -> None:
        if self._loaded and self._tts is not None:
            return
        TTS, TTS_Config = self._import_gpt_sovits()

        model_dir = self.config.get("model_dir") or ""
        if not model_dir:
            raise ModelLoadError(
                "Missing config field: model_dir",
                details={"provider": self.name},
            )
        version = self.config.get("version", "v2Pro")
        paths = self._build_paths(model_dir, version)

        target_device = resolve_device(self.config.get("device"))
        is_half = str(self.config.get("is_half", "false")).lower() == "true"
        if target_device == "cpu" and is_half:
            log.warning("gpt_sovits.fp16_disabled_on_cpu", provider=self.name)
            is_half = False

        configs_dict = {
            "custom": {
                **paths,
                "version": version,
                "device": target_device,
                "is_half": is_half,
            }
        }

        used_mb_before, total_mb = vram_usage_mb()
        model_size_mb = _dir_size_mb(model_dir)
        log.info(
            "gpt_sovits.load.start",
            provider=self.name,
            model_dir=model_dir,
            version=version,
            target_device=target_device,
            is_half=is_half,
            model_size_mb=model_size_mb,
            vram_used_mb_before=used_mb_before,
            vram_total_mb=total_mb,
            vram_free_mb=max(0, total_mb - used_mb_before),
        )

        try:
            self._tts = TTS(configs_dict)
            sr = getattr(getattr(self._tts, "configs", None), "sampling_rate", None)
            if isinstance(sr, int) and sr > 0:
                self._sample_rate = sr
            used_mb_after, _ = vram_usage_mb()
            log.info(
                "gpt_sovits.load.done",
                provider=self.name,
                device=target_device,
                sample_rate=self._sample_rate,
                vram_used_mb_after=used_mb_after,
                vram_consumed_mb=max(0, used_mb_after - used_mb_before),
            )
            self._loaded = True
        except FileNotFoundError as e:
            raise ModelLoadError(
                f"GPT-SoVITS missing model file: {e}",
                details={"provider": self.name, "model_dir": model_dir},
            ) from e
        except Exception as e:
            raise ModelLoadError(
                f"Failed to load GPT-SoVITS: {e}",
                details={"provider": self.name, "model_size_mb": model_size_mb},
            ) from e

    def unload(self) -> None:
        self._tts = None
        self._loaded = False
        try:
            import torch  # type: ignore[import-not-found]
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass

    def info(self) -> ProviderInfo:
        return ProviderInfo(
            kind="cloning",
            name=self.name,
            class_name=type(self).__name__,
            loaded=self._loaded,
            extra={
                "device": self.config.get("device", "auto"),
                "version": self.config.get("version", "v2Pro"),
            },
        )

    def synthesize(
        self,
        text: str,
        voice_id: str,  # noqa: ARG002 — GPT-SoVITS 用 ref_audio_path 而非 voice_id
        speed: float = 1.0,
        format: str = "wav",
        reference_audio_path: str | None = None,
    ) -> bytes:
        import numpy as np

        if self._tts is None:
            raise InferenceError(
                "GPT-SoVITS not loaded; call load() first",
                details={"provider": self.name},
            )
        if not reference_audio_path:
            raise InferenceError(
                "GPT-SoVITS is zero-shot: reference_audio_path is required",
                details={"provider": self.name},
            )
        if format not in ("wav",):
            raise InferenceError(
                f"GPT-SoVITS currently only emits WAV; got format={format!r}",
                details={"provider": self.name},
            )
        prompt_text = str(self.config.get("prompt_text") or "").strip()
        if not prompt_text:
            raise InferenceError(
                "GPT-SoVITS v2Pro requires prompt_text (transcript of the reference audio). "
                "Set prompt_text in this Provider's config — must match what the speaker says "
                "in the reference WAV. Cross-lingual: also set prompt_lang to the reference "
                "audio's language.",
                details={"provider": self.name},
            )

        try:
            top_k = int(self.config.get("top_k", 15))
        except (TypeError, ValueError):
            top_k = 15
        try:
            top_p = float(self.config.get("top_p", 1.0))
        except (TypeError, ValueError):
            top_p = 1.0
        try:
            temperature = float(self.config.get("temperature", 1.0))
        except (TypeError, ValueError):
            temperature = 1.0
        prompt_lang = self.config.get("prompt_lang", "auto") or "auto"
        text_split_method = self.config.get("text_split_method", "cut5")

        inputs = {
            "text": text,
            "text_lang": "zh",  # 当前 Provider 专用于"输出中文"；后续如需多语扩展再加 config
            "ref_audio_path": reference_audio_path,
            "prompt_text": prompt_text,
            "prompt_lang": prompt_lang,
            "top_k": top_k,
            "top_p": top_p,
            "temperature": temperature,
            "text_split_method": text_split_method,
            "speed_factor": float(speed),
            "return_fragment": False,
            "streaming_mode": False,
        }

        try:
            chunks = []
            sr = self._sample_rate
            for chunk_sr, chunk_audio in self._tts.run(inputs):
                sr = chunk_sr
                chunks.append(np.asarray(chunk_audio, dtype=np.int16))
            if not chunks:
                raise InferenceError(
                    "GPT-SoVITS produced no audio (empty stream)",
                    details={"provider": self.name},
                )
            audio = np.concatenate(chunks)
        except InferenceError:
            raise
        except Exception as e:
            raise InferenceError(
                f"GPT-SoVITS synthesis failed: {e}",
                details={"provider": self.name, "reference": reference_audio_path},
            ) from e

        return _i16_to_wav_bytes(audio, sr)

    def list_voices(self) -> list[Voice]:
        # 无内置音色；可用音色由 voice_refs 表（外部）维护
        return []

    def clone_voice(
        self, reference_audio_path: str, speaker_name: str | None = None,  # noqa: ARG002
    ) -> str:
        """生成 voice_id；reference 实际持久化由 worker 层负责。"""
        return "gs_" + uuid.uuid4().hex[:12]
