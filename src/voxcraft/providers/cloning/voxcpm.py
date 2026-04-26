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
from pathlib import Path

import structlog

from voxcraft.errors import InferenceError, ModelLoadError
from voxcraft.providers import capabilities
from voxcraft.providers.base import CloningProvider, ConfigField, ProviderInfo, Voice
from voxcraft.runtime.gpu import resolve_device, vram_usage_mb


log = structlog.get_logger()


def _dir_size_mb(path: str | None) -> int:
    """模型目录总字节 / 1024² → MB；路径无效或为空返回 0。"""
    if not path:
        return 0
    try:
        total = sum(
            f.stat().st_size for f in Path(path).rglob("*") if f.is_file()
        )
        return int(total // (1024 * 1024))
    except OSError:
        return 0


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
            "prompt_text", "Prompt 文本", "str", default="",
            help="参考音频对应的转写文字。VoxCPM 1.x（0.5B）必填；VoxCPM2 可留空走基础克隆，填上则升级到 ultimate cloning 保真度更高",
        ),
    ]

    def __init__(self, name: str, config: dict) -> None:
        super().__init__(name, config)
        self._model = None
        self._sample_rate: int = 24000  # VoxCPM 默认；load 后从模型读取覆盖

    def load(self) -> None:
        if self._loaded and self._model is not None:
            return
        # VoxCPM 内部对部分前向走 torch.compile；torch._dynamo trace einops 0.8.2 的
        # `str.isalnum(char)` unbound 调用时挂（dynamo polyfill 不支持该调用形式），
        # 抛 InternalTorchDynamoError 直接打到 Provider 层。
        # suppress_errors 是软开关、时机偏晚——这里把 torch.compile 全局 monkey-patch
        # 成 identity，让 voxcpm 内部所有 @torch.compile / torch.compile(...) 调用
        # 直接退化为 eager；同时 Dockerfile 设 TORCHDYNAMO_DISABLE=1 作进程级兜底。
        # Pascal 卡 compile 收益本就有限，eager 可接受。
        try:
            import torch  # type: ignore[import-not-found]

            def _noop_compile(model=None, **_kw):
                if model is None:
                    return lambda fn: fn  # 当装饰器用：@torch.compile(...)
                return model  # 当函数用：torch.compile(model)

            torch.compile = _noop_compile  # type: ignore[assignment]
            try:
                import torch._dynamo  # type: ignore[import-not-found]
                torch._dynamo.config.suppress_errors = True
                torch._dynamo.config.disable = True
            except ImportError:
                pass
        except ImportError:
            pass

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
        target_device = resolve_device(self.config.get("device"))
        used_mb_before, total_mb = vram_usage_mb()
        # voxcpm 库（VoxCPM2Model.from_local）的实际加载顺序：
        #   1) torch.load(map_location="cpu") 先把权重读进 CPU
        #   2) model 也在 CPU 构造
        #   3) model.load_state_dict(state_dict)：state_dict + model 同时持有，峰值 ~ 2× 模型字节
        #   4) 最后才 model.to(cuda)
        # 8GB 容器加载 VoxCPM 2 (~4GB bfloat16) 会在第 3 步爆 OOM，被 SIGKILL；
        # 用户看到的现象是 "GPU 空闲 + RAM 满载"——其实根本没机会传到 GPU。
        model_size_mb = _dir_size_mb(self.config.get("model_dir"))
        ram_peak_estimate_mb = model_size_mb * 2  # state_dict + model 共存
        log.info(
            "voxcpm.load.start",
            provider=self.name,
            model_dir=self.config.get("model_dir"),
            target_device=target_device,
            load_denoiser=load_denoiser,
            model_size_mb=model_size_mb,
            ram_peak_estimate_mb=ram_peak_estimate_mb,
            vram_used_mb_before=used_mb_before,
            vram_total_mb=total_mb,
            vram_free_mb=max(0, total_mb - used_mb_before),
            note=(
                "voxcpm loads to CPU first (state_dict + model coexist), "
                "then transfers to target_device; container RAM must hold the peak"
            ),
        )
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

            used_mb_after, _ = vram_usage_mb()
            log.info(
                "voxcpm.load.done",
                provider=self.name,
                device=target_device,
                sample_rate=self._sample_rate,
                vram_used_mb_after=used_mb_after,
                vram_consumed_mb=max(0, used_mb_after - used_mb_before),
            )
            self._loaded = True
        except KeyError as e:
            raise ModelLoadError(
                f"Missing config field: {e.args[0]}",
                details={"provider": self.name},
            ) from e
        except MemoryError as e:
            raise ModelLoadError(
                f"VoxCPM load OOM (CPU): {e}. "
                f"模型 {model_size_mb}MB，加载峰值约 {ram_peak_estimate_mb}MB CPU RAM。"
                "voxcpm 库设计先 CPU 全量加载再传 GPU，容器 RAM 不够即使 GPU 空闲也会被杀。"
                "建议：① 容器 RAM 提升到 ≥ 估算峰值的 1.5 倍；② 换更小模型（voxcpm-0.5b）；"
                "③ device=cpu 时 RAM 需求不变（仍有这一步），只是不再传 GPU。",
                details={"provider": self.name, "model_size_mb": model_size_mb},
            ) from e
        except Exception as e:
            raise ModelLoadError(
                f"Failed to load VoxCPM: {e}",
                details={"provider": self.name, "model_size_mb": model_size_mb},
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

        # voxcpm 包是 facade：VoxCPM.from_pretrained 根据 config.json 的 architecture
        # 字段加载 VoxCPMModel (v1, 如 VoxCPM-0.5B) 或 VoxCPM2Model (v2)。
        # generate() 是统一入口，但 validation 规则按内部模型分支：
        #   - prompt_wav_path / prompt_text：v1 v2 都强制配对，少一个就抛
        #   - reference_wav_path：仅 v2 支持，v1 传会抛 "only supported with VoxCPM2"
        # v1 (0.5B) 的唯一克隆路径是 prompt_wav_path + prompt_text 同传——必须有转写文字。
        # v2 还可以走"基础克隆"（仅 reference_wav_path，无需转写）。
        try:
            from voxcpm.model.voxcpm2 import VoxCPM2Model  # type: ignore[import-not-found]
            is_v2 = isinstance(getattr(self._model, "tts_model", None), VoxCPM2Model)
        except (ImportError, AttributeError):
            inner = getattr(self._model, "tts_model", self._model)
            is_v2 = type(inner).__name__ == "VoxCPM2Model"

        gen_kwargs: dict = {
            "text": text,
            "cfg_value": cfg_value,
            "inference_timesteps": inference_timesteps,
        }
        if is_v2:
            if prompt_text:
                # Ultimate Cloning：三参数同传（最高保真度）
                gen_kwargs["prompt_wav_path"] = reference_audio_path
                gen_kwargs["prompt_text"] = prompt_text
                gen_kwargs["reference_wav_path"] = reference_audio_path
            else:
                # 基础克隆（v2 主推，无需转写）
                gen_kwargs["reference_wav_path"] = reference_audio_path
        else:
            # v1.x：必须 prompt_wav_path + prompt_text 同传，否则 voxcpm 直接抛错
            if not prompt_text:
                raise InferenceError(
                    "VoxCPM 1.x (e.g. VoxCPM-0.5B) requires both reference audio AND its "
                    "transcript. Set `prompt_text` in this Provider's config (the words "
                    "that are spoken in the reference audio), or switch to VoxCPM2 which "
                    "supports zero-shot cloning without transcript.",
                    details={"provider": self.name, "model_arch": "voxcpm-v1"},
                )
            gen_kwargs["prompt_wav_path"] = reference_audio_path
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
