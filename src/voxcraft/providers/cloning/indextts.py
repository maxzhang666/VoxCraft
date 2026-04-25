"""IndexTTS-2 声纹克隆（B 站，CPML 非商业许可，自托管个人使用）。

API 来源：index-tts/index-tts v2.0.0 README + indextts/infer_v2.py
- IndexTTS2(cfg_path, model_dir, use_fp16, device, use_cuda_kernel, use_deepspeed) 构造
- model.infer(spk_audio_prompt, text, output_path, ...) 推理；output_path truthy → 写 wav 文件
- 采样率硬编码 22050（infer_v2 内部）；output_path 为 falsy 时返回 (sr, np.int16) 元组

集成策略：
- clone_voice：仅生成 voice_id；reference 持久化由 worker 层完成（zero-shot 模型无 enroll）
- synthesize：infer 写 tmp wav → 读字节返回；reference_audio_path 由 worker 反查 voice_refs 提供

注意：
- IndexTTS2 import 时会把 os.environ['HF_HUB_CACHE'] 强制写成 './checkpoints/hf_cache'
  （infer_v2.py 第 4 行）；本模块 import 后立即恢复原值，避免污染全局 HF cache
- 首次构造会从 HF 自动拉 amphion/MaskGCT、funasr/campplus、facebook/w2v-bert-2.0 等子模型
  （~1.5GB），不计入主仓库 size_mb
"""
from __future__ import annotations

import os
import tempfile
import uuid
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


class IndexTtsProvider(CloningProvider):
    LABEL = "IndexTTS-2（B 站，开源个人使用）"
    CAPABILITIES = frozenset({capabilities.CLONE})
    CONFIG_SCHEMA = [
        ConfigField(
            "model_dir", "模型目录", "path", required=True,
            help="本地目录或 HF repo id（IndexTeam/IndexTTS-2）；需含 config.yaml + gpt.pth + s2mel.pth",
        ),
        ConfigField(
            "device", "设备", "enum",
            options=("auto", "cpu", "cuda"), default="auto",
        ),
        ConfigField(
            "use_fp16", "FP16 推理", "enum",
            options=("true", "false"), default="false",
            help="GPU 上启用以减半显存与加速；CPU 不支持",
        ),
        ConfigField(
            "use_cuda_kernel", "启用 CUDA Kernel", "enum",
            options=("auto", "true", "false"), default="auto",
            help="自定义 CUDA op；auto 让 IndexTTS 自行判断",
        ),
        ConfigField(
            "use_deepspeed", "启用 DeepSpeed", "enum",
            options=("true", "false"), default="false",
            help="GPU 上配合 DeepSpeed 加速；需另行安装 deepspeed",
        ),
        ConfigField(
            "emo_alpha", "情绪强度", "str", default="1.0",
            help="0.0–1.0；情绪参考音频/向量的混合权重",
        ),
    ]

    def __init__(self, name: str, config: dict) -> None:
        super().__init__(name, config)
        self._model = None
        self._sample_rate: int = 22050  # IndexTTS-2 内部硬编码

    def _import_indextts(self):
        """导入 IndexTTS2 类；恢复其顶层污染的 HF_HUB_CACHE。"""
        hf_cache_orig = os.environ.get("HF_HUB_CACHE")
        try:
            from indextts.infer_v2 import IndexTTS2  # type: ignore[import-not-found]
        except ImportError as e:
            raise ModelLoadError(
                "indextts not installed; rebuild image (uv sync 会通过 git+ source 拉 IndexTTS v2.0.0)",
                details={"provider": self.name},
            ) from e
        finally:
            # infer_v2.py 顶层执行 os.environ['HF_HUB_CACHE'] = './checkpoints/hf_cache'
            # 立即恢复，避免污染全局 HF cache 路径
            if hf_cache_orig is None:
                os.environ.pop("HF_HUB_CACHE", None)
            else:
                os.environ["HF_HUB_CACHE"] = hf_cache_orig
        return IndexTTS2

    def load(self) -> None:
        if self._loaded and self._model is not None:
            return
        IndexTTS2 = self._import_indextts()

        model_dir = self.config.get("model_dir") or ""
        if not model_dir:
            raise ModelLoadError(
                "Missing config field: model_dir",
                details={"provider": self.name},
            )
        cfg_path = str(Path(model_dir) / "config.yaml")
        if not Path(cfg_path).is_file():
            raise ModelLoadError(
                f"IndexTTS config.yaml not found at {cfg_path}; "
                "确保已下载 IndexTeam/IndexTTS-2 仓库到此目录",
                details={"provider": self.name, "cfg_path": cfg_path},
            )

        target_device = resolve_device(self.config.get("device"))
        use_fp16 = str(self.config.get("use_fp16", "false")).lower() == "true"
        use_deepspeed = str(self.config.get("use_deepspeed", "false")).lower() == "true"
        kernel_cfg = str(self.config.get("use_cuda_kernel", "auto")).lower()
        use_cuda_kernel: bool | None
        if kernel_cfg == "true":
            use_cuda_kernel = True
        elif kernel_cfg == "false":
            use_cuda_kernel = False
        else:
            use_cuda_kernel = None  # IndexTTS auto

        used_mb_before, total_mb = vram_usage_mb()
        model_size_mb = _dir_size_mb(model_dir)
        # IndexTTS-2 同 voxcpm：torch.load(map_location=cpu) → state_dict + model 共存 → .to(device)
        # 主权重 ~4.3GB，加载峰值 RAM 约 2× = 8.6GB；含 qwen emo 子模型再加 ~1.2GB
        ram_peak_estimate_mb = model_size_mb * 2

        log.info(
            "indextts.load.start",
            provider=self.name,
            model_dir=model_dir,
            target_device=target_device,
            use_fp16=use_fp16,
            use_cuda_kernel=use_cuda_kernel,
            use_deepspeed=use_deepspeed,
            model_size_mb=model_size_mb,
            ram_peak_estimate_mb=ram_peak_estimate_mb,
            vram_used_mb_before=used_mb_before,
            vram_total_mb=total_mb,
            vram_free_mb=max(0, total_mb - used_mb_before),
            note=(
                "IndexTTS-2 loads to CPU first then transfers; container RAM must hold "
                "the peak. First load also fetches MaskGCT/campplus/w2v-bert-2.0 from HF."
            ),
        )

        try:
            self._model = IndexTTS2(
                cfg_path=cfg_path,
                model_dir=model_dir,
                use_fp16=use_fp16,
                device=target_device,
                use_cuda_kernel=use_cuda_kernel,
                use_deepspeed=use_deepspeed,
            )
            used_mb_after, _ = vram_usage_mb()
            log.info(
                "indextts.load.done",
                provider=self.name,
                device=target_device,
                sample_rate=self._sample_rate,
                vram_used_mb_after=used_mb_after,
                vram_consumed_mb=max(0, used_mb_after - used_mb_before),
            )
            self._loaded = True
        except MemoryError as e:
            raise ModelLoadError(
                f"IndexTTS-2 load OOM (CPU): {e}. "
                f"模型 {model_size_mb}MB，加载峰值约 {ram_peak_estimate_mb}MB CPU RAM。"
                "IndexTTS-2 设计先 CPU 全量加载再传 GPU，容器 RAM 不够即使 GPU 空闲也会被杀。"
                "建议：① 容器 RAM 提升到 ≥ 估算峰值的 1.5 倍（≥ 8GB 推荐）；"
                "② device=cpu 时 RAM 需求不变（仍有这一步），只是不再传 GPU。",
                details={"provider": self.name, "model_size_mb": model_size_mb},
            ) from e
        except FileNotFoundError as e:
            raise ModelLoadError(
                f"IndexTTS-2 missing model file: {e}. "
                "确保 model_dir 含 config.yaml + gpt.pth + s2mel.pth + bpe.model + "
                "feat1.pt + feat2.pt + wav2vec2bert_stats.pt + qwen0.6bemo4-merge/ 子目录",
                details={"provider": self.name, "model_dir": model_dir},
            ) from e
        except Exception as e:
            raise ModelLoadError(
                f"Failed to load IndexTTS-2: {e}",
                details={"provider": self.name, "model_size_mb": model_size_mb},
            ) from e

    def unload(self) -> None:
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
            extra={
                "device": self.config.get("device", "auto"),
                "non_commercial": True,
            },
        )

    def synthesize(
        self,
        text: str,
        voice_id: str,  # noqa: ARG002 — IndexTTS 用 reference_audio_path 而非 voice_id
        speed: float = 1.0,  # noqa: ARG002 — IndexTTS-2 不直接暴露 speed；后续可走 resample
        format: str = "wav",
        reference_audio_path: str | None = None,
    ) -> bytes:
        if self._model is None:
            raise InferenceError(
                "IndexTTS-2 not loaded; call load() first",
                details={"provider": self.name},
            )
        if not reference_audio_path:
            raise InferenceError(
                "IndexTTS-2 is zero-shot: reference_audio_path is required (no built-in voices)",
                details={"provider": self.name},
            )
        if format not in ("wav",):
            raise InferenceError(
                f"IndexTTS-2 currently only emits WAV; got format={format!r}",
                details={"provider": self.name},
            )

        try:
            emo_alpha = float(self.config.get("emo_alpha", 1.0))
        except (TypeError, ValueError):
            emo_alpha = 1.0

        # infer 写到临时文件，读完即删，避免落到磁盘
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            try:
                self._model.infer(  # type: ignore[union-attr]
                    spk_audio_prompt=reference_audio_path,
                    text=text,
                    output_path=tmp_path,
                    emo_alpha=emo_alpha,
                    verbose=False,
                )
            except Exception as e:
                raise InferenceError(
                    f"IndexTTS-2 synthesis failed: {e}",
                    details={"provider": self.name, "reference": reference_audio_path},
                ) from e

            with open(tmp_path, "rb") as f:
                return f.read()
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    def list_voices(self) -> list[Voice]:
        # IndexTTS-2 无内置音色；可用音色由 voice_refs 表（外部）维护
        return []

    def clone_voice(
        self, reference_audio_path: str, speaker_name: str | None = None,  # noqa: ARG002
    ) -> str:
        """生成 voice_id；reference 实际持久化由 worker 层负责。

        IndexTTS-2 zero-shot 模型本身无 enroll 步骤——这里只是分配一个 stable id，
        后续 synthesize 时通过 voice_id → voice_refs.reference_audio_path 反查。
        """
        return "ix_" + uuid.uuid4().hex[:12]
