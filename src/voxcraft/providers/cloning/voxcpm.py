"""VoxCPM 声纹克隆（Apache 2.0，商业友好）。

API 来源：OpenBMB/VoxCPM README + voxcpm.readthedocs.io quickstart
- VoxCPM.from_pretrained(model_path, load_denoiser=False) 构造
- model.generate(text, prompt_wav_path=..., cfg_value=..., inference_timesteps=...)
  返回 numpy ndarray（float32），采样率从 model.tts_model.sample_rate 取
- prompt_wav_path 是参考声纹音频路径；可选传 prompt_text + reference_wav_path 走
  ultimate cloning 路径以提升保真度

VoxCraft 集成策略：
- clone_voice：仅生成 voice_id；不调模型（VoxCPM zero-shot 模型本身无状态，
  reference 持久化由 worker 层完成；本方法可被 /api/tts/clone 业务流路径调用）
- synthesize：根据 voice_id + reference_audio_path 调 model.generate；
  参考音频路径由 worker 层从 voice_refs 表反查后传入
"""
from __future__ import annotations

import io
import uuid
import wave

from voxcraft.errors import InferenceError, ModelLoadError
from voxcraft.providers import capabilities
from voxcraft.providers.base import CloningProvider, ConfigField, ProviderInfo, Voice


def _f32_to_wav_bytes(audio, sample_rate: int) -> bytes:
    """把 VoxCPM 输出的 numpy float32 数组（[-1, 1]）打包为 16-bit PCM WAV bytes。"""
    import numpy as np

    arr = np.asarray(audio, dtype=np.float32)
    if arr.ndim > 1:
        arr = arr.reshape(-1)
    arr = np.clip(arr, -1.0, 1.0)
    pcm16 = (arr * 32767.0).astype(np.int16)

    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm16.tobytes())
    return buf.getvalue()


class VoxCpmCloningProvider(CloningProvider):
    LABEL = "VoxCPM（开源声纹克隆）"
    CAPABILITIES = frozenset({capabilities.CLONE})
    CONFIG_SCHEMA = [
        ConfigField(
            "model_dir", "模型目录", "path", required=True,
            help="本地目录或 HF repo id（如 openbmb/VoxCPM2）",
        ),
        ConfigField(
            "device", "设备", "enum",
            options=("auto", "cpu", "cuda"), default="auto",
        ),
        ConfigField(
            "load_denoiser", "加载降噪器", "enum",
            options=("true", "false"), default="false",
            help="增强参考音频/Prompt 时使用；常规合成留 false 节省显存",
        ),
        ConfigField(
            "cfg_value", "CFG 引导强度", "str", default="2.0",
            help="Classifier-Free Guidance 系数；建议 1.5–3.0",
        ),
        ConfigField(
            "inference_timesteps", "推理步数", "int", default=10,
            help="扩散去噪步数；增大→更精细，速度变慢",
        ),
        ConfigField(
            "prompt_text", "默认 Prompt 文本", "str", default="",
            help="若提供，开启 ultimate cloning（保真度更高）；建议填参考音频对应的文字",
        ),
    ]

    def __init__(self, name: str, config: dict) -> None:
        super().__init__(name, config)
        self._model = None
        self._sample_rate: int = 24000  # VoxCPM 默认；load 后从模型读取覆盖

    def load(self) -> None:
        if self._loaded and self._model is not None:
            return
        try:
            from voxcpm import VoxCPM  # type: ignore[import-not-found]
        except ImportError as e:
            raise ModelLoadError(
                "voxcpm not installed; install on deployment host: pip install voxcpm",
                details={"provider": self.name},
            ) from e
        except OSError as e:
            # mac arm64 上 voxcpm 拉的 torchaudio 与 torch wheel 的 C++ ABI 可能不匹配
            # （Linux GPU 部署不会触发）；用 ModelLoadError 暴露给上层而非裸 OSError
            raise ModelLoadError(
                f"voxcpm import failed (likely torch/torchaudio ABI mismatch): {e}",
                details={"provider": self.name},
            ) from e

        load_denoiser = str(self.config.get("load_denoiser", "false")).lower() == "true"
        try:
            model_dir = self.config["model_dir"]
            self._model = VoxCPM.from_pretrained(
                model_dir,
                load_denoiser=load_denoiser,
            )
            # 设备迁移：VoxCPM 不在构造参数里接受 device，用 .to() 移动
            device = self.config.get("device", "auto")
            if device == "auto":
                try:
                    import torch  # type: ignore[import-not-found]
                    device = "cuda" if torch.cuda.is_available() else "cpu"
                except ImportError:
                    device = "cpu"
            try:
                # 部分模型对象不直接暴露 .to()；忽略时仍按构造的默认设备跑
                self._model.to(device)  # type: ignore[attr-defined]
            except (AttributeError, TypeError):
                pass

            sr = getattr(getattr(self._model, "tts_model", None), "sample_rate", None)
            if isinstance(sr, int) and sr > 0:
                self._sample_rate = sr

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
        # 显式释放模型 + 清 CUDA cache（如果有 torch）
        self._model = None
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
            extra={"device": self.config.get("device", "cpu")},
        )

    def synthesize(
        self,
        text: str,
        voice_id: str,  # noqa: ARG002 — VoxCPM 用 reference_audio_path 而非 voice_id
        speed: float = 1.0,  # noqa: ARG002 — VoxCPM 不直接暴露 speed；后续按需 resample 实现
        format: str = "wav",
        reference_audio_path: str | None = None,
    ) -> bytes:
        if self._model is None:
            raise InferenceError(
                "VoxCPM not loaded; call load() first",
                details={"provider": self.name},
            )
        if not reference_audio_path:
            raise InferenceError(
                "VoxCPM is zero-shot: reference_audio_path is required (no built-in voices)",
                details={"provider": self.name},
            )
        if format not in ("wav",):
            # MP3/OGG 解码器层后续可做；先只支持 WAV，避免静默生成错误格式
            raise InferenceError(
                f"VoxCPM currently only emits WAV; got format={format!r}",
                details={"provider": self.name},
            )

        try:
            cfg_value = float(self.config.get("cfg_value", 2.0))
        except (TypeError, ValueError):
            cfg_value = 2.0
        try:
            inference_timesteps = int(self.config.get("inference_timesteps", 10))
        except (TypeError, ValueError):
            inference_timesteps = 10
        prompt_text = str(self.config.get("prompt_text") or "").strip()

        gen_kwargs: dict = {
            "text": text,
            "prompt_wav_path": reference_audio_path,
            "cfg_value": cfg_value,
            "inference_timesteps": inference_timesteps,
        }
        # ultimate cloning：prompt_text 提供时一并传，提升保真度
        if prompt_text:
            gen_kwargs["prompt_text"] = prompt_text

        try:
            audio = self._model.generate(**gen_kwargs)  # type: ignore[union-attr]
        except Exception as e:
            raise InferenceError(
                f"VoxCPM synthesis failed: {e}",
                details={"provider": self.name, "reference": reference_audio_path},
            ) from e

        return _f32_to_wav_bytes(audio, self._sample_rate)

    def list_voices(self) -> list[Voice]:
        # VoxCPM 无内置音色；可用音色由 voice_refs 表（外部）维护
        return []

    def clone_voice(
        self, reference_audio_path: str, speaker_name: str | None = None,  # noqa: ARG002
    ) -> str:
        """生成 voice_id；reference 实际持久化由 worker 层负责。

        VoxCPM zero-shot 模型本身无 enroll 步骤——这里只是分配一个 stable id，
        后续 synthesize 时通过 voice_id → voice_refs.reference_audio_path 反查。
        """
        return "vx_" + uuid.uuid4().hex[:12]
