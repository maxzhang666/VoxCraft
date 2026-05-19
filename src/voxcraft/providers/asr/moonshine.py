"""Moonshine（moonshine-ai/moonshine）ONNX 后端的 AsrProvider 实现。

Moonshine 是一组为"短音频 + 低延迟"优化的 ASR 模型：参数比同档 Whisper 小 6×、
ONNX 后端 CPU 即可 <300ms 出结果、输入长度可变（无 30s 窗口浪费）。

集成边界 & 已知限制（实事求是）：

1) **无 segment 级时间戳**。useful-moonshine-onnx.transcribe() 返回平铺文本，
   没有 segment.start/end。本 Provider 把整段输出包成单 segment [0, duration]
   满足 AsrResult 契约；够 /api/asr 纯文本场景。video_translate 字幕对齐需要
   细粒度时间戳，那条路径仍应优先选 Whisper——上游设计如此，非本 Provider 限制。

2) **模型在 VoxCraft 模型库可见但缓存路径要对齐**。catalog 里有一条 `moonshine`
   entry 指向 `UsefulSensors/moonshine`（同一个 repo 内含 tiny + base 两个 size
   的 ONNX 子目录），下载后两个 size 都到位。但 useful-moonshine-onnx 库运行时
   走的是 `huggingface_hub` 默认 cache 路径（HF_HOME / HF_HUB_CACHE），与 VoxCraft
   `snapshot_download(local_dir=...)` 落盘位置不一致——想让两者共享存储、避免
   首次 transcribe 再下一遍，**容器环境里把 HF_HOME 指向同一个持久卷**（如
   `HF_HOME=/app/data/hf-home`）。不配也能用，只是首次推理多一次 ~300MB 下载。

3) **ExecutionProvider 选择是只读的**。useful-moonshine-onnx.transcribe() 的
   高层 API **不接受 providers 参数**——内部走默认 InferenceSession，pip 装了
   onnxruntime-gpu 就自动 CUDA EP，没装就 CPU EP。本 Provider 的 `device`
   config 只做 **assertion**（device='cuda' 但 CUDA EP 不可用 → load 时 raise，
   避免运行到一半才崩），不能像 WhisperProvider 那样真正切换设备。这意味着：
   - 想强制 CPU 跑 → 镜像里别装 onnxruntime-gpu（当前 pyproject 装了，所以不可控）
   - 想强制 CUDA 跑 → 装 onnxruntime-gpu 即可，库自动用
   - device='auto' 是当前行为的描述，不是控制开关
   future：如果上游暴露 `providers=` kwarg 或我们直接调下层 InferenceSession，
   再补回完整控制。

Config 字段：
- model_name: enum   "moonshine/tiny" / "moonshine/base" + 语种特化（zh/ja/ko），
                      也可手动改 DB 写其他 model_name 字符串。首次推理触发自动下载
- language:  str     ISO 语种码（en/zh/...），只做结果元数据；具体语种由 model_name 决定
- device:    enum    "auto"/"cpu"/"cuda"——见上 3) 的限制
- max_tokens_per_second: float   CJK 建议 13.0；英文场景库默认 6.5；留空跟库默认
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


def _as_float(v: Any, default: float) -> float:
    if v is None or v == "":
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _audio_duration_seconds(path: str) -> float:
    """读音频元数据拿时长；失败返回 0.0（不致命）。"""
    try:
        import soundfile as sf
        info = sf.info(path)
        if info.samplerate:
            return float(info.frames) / float(info.samplerate)
    except Exception:  # noqa: BLE001
        pass
    return 0.0


class MoonshineProvider(AsrProvider):
    LABEL = "Moonshine（边缘端低延迟 ASR / ONNX）"
    CONFIG_SCHEMA = [
        ConfigField(
            "model_name", "模型", "enum",
            options=(
                "moonshine/tiny",
                "moonshine/base",
                # 语种特化（v2）；用户也可自行填别的字符串
                "moonshine/tiny-zh",
                "moonshine/base-zh",
                "moonshine/tiny-ja",
                "moonshine/base-ja",
                "moonshine/tiny-ko",
                "moonshine/base-ko",
            ),
            default="moonshine/base",
            required=True,
            help="moonshine/tiny ≈ 27M、moonshine/base ≈ 61M；语种特化版精度更高。"
            "第一次使用会从 HF 拉模型到 HF_HOME 缓存",
        ),
        ConfigField(
            "language", "目标语种（结果标记用）", "str", default="en",
            help="ISO 语种码（en/zh/ja/ko/...）。Moonshine 模型多数已绑定语种或"
            "多语种统一处理，本字段仅用于在结果里标记语言归属",
        ),
        ConfigField(
            "device", "设备", "enum",
            options=("auto", "cpu", "cuda"), default="auto",
            help="auto 优先选 CUDAExecutionProvider，缺则 CPU。Moonshine 模型小，"
            "CPU 已经能 100ms 量级，多数场景无需 GPU",
        ),
        ConfigField(
            "max_tokens_per_second", "Max tokens / s", "str", default="",
            help="非拉丁字母语种（中文 / 日文 / 韩文）建议填 13.0；留空走库内置"
            "默认（英文场景 6.5）。这是 Moonshine 解码停机准则，调大避免长音频截断",
        ),
    ]

    def __init__(self, name: str, config: dict) -> None:
        super().__init__(name, config)
        # Moonshine 库内部按 model name 缓存模型实例，本 Provider 不持有重对象——
        # load() 仅做"探活 + 预热"。卸载也只是清标记。
        self._model_name: str | None = None

    def _resolve_providers(self) -> list[str]:
        """根据 device config 决定 onnxruntime 的 ExecutionProvider 顺序。

        Moonshine 内部如果接受 providers 参数则透传；不接受则只能靠环境（默认顺序）。
        多数实测：装了 onnxruntime-gpu 就自动选 CUDA，否则 CPU。这里返回供日志输出。
        """
        device = (self.config.get("device") or "auto").lower()
        try:
            import onnxruntime as ort  # noqa: PLC0415
            available = set(ort.get_available_providers())
        except ImportError:
            return ["CPUExecutionProvider"]

        if device == "cpu":
            return ["CPUExecutionProvider"]
        if device == "cuda":
            if "CUDAExecutionProvider" not in available:
                raise ModelLoadError(
                    "device='cuda' 但 onnxruntime CUDA EP 不可用——请确认装了 "
                    "onnxruntime-gpu 而非 onnxruntime，且 CUDA/cuDNN 与驱动匹配",
                    details={"provider": self.name, "available": sorted(available)},
                )
            return ["CUDAExecutionProvider", "CPUExecutionProvider"]
        # auto：能用 CUDA 就 CUDA，不强求
        if "CUDAExecutionProvider" in available:
            return ["CUDAExecutionProvider", "CPUExecutionProvider"]
        return ["CPUExecutionProvider"]

    def load(self) -> None:
        if self._loaded:
            return
        model_name = self.config.get("model_name") or "moonshine/base"
        try:
            # useful-moonshine-onnx 暴露的顶层 API：moonshine_onnx.transcribe(path, name)
            import moonshine_onnx  # noqa: F401, PLC0415
        except ImportError as e:
            raise ModelLoadError(
                "moonshine_onnx 未安装。请检查 pyproject.toml 是否包含 "
                "useful-moonshine-onnx 依赖",
                details={"provider": self.name, "import_error": str(e)},
            ) from e

        # 探活：构造 providers 列表确保运行环境 OK；模型首次 transcribe 时才会真
        # 下载，避免 load() 阻塞 LRU 太久（HF snapshot 可能慢）
        providers = self._resolve_providers()
        self._model_name = model_name
        self._loaded = True
        # 把决定的 providers 透传给 info()
        self.config.setdefault("_resolved_providers", providers)

    def unload(self) -> None:
        # Moonshine 库自己管模型缓存；Provider 端清标记即可。下一次 load 走快路径
        self._model_name = None
        self._loaded = False

    def info(self) -> ProviderInfo:
        return ProviderInfo(
            kind="asr",
            name=self.name,
            class_name=type(self).__name__,
            loaded=self._loaded,
            extra={
                "model_name": self.config.get("model_name", "moonshine/base"),
                "device": self.config.get("device", "auto"),
                "providers": self.config.get("_resolved_providers"),
            },
        )

    def transcribe(
        self,
        audio_path: str,
        language: str | None = None,
        progress_cb=None,
        options: dict | None = None,
    ) -> AsrResult:
        if not self._loaded or self._model_name is None:
            raise InferenceError(
                "MoonshineProvider not loaded; call load() first",
                details={"provider": self.name},
            )

        # options 允许请求级覆盖 model_name / max_tokens_per_second（用法和
        # WhisperProvider._build_transcribe_kwargs 同理；这里 Moonshine 可调点少，
        # 不抽取单独 helper）
        opts = options or {}
        model_name = opts.get("model_name") or self._model_name
        max_tps = _as_float(
            opts.get("max_tokens_per_second")
            if opts.get("max_tokens_per_second") not in (None, "")
            else self.config.get("max_tokens_per_second"),
            0.0,
        )

        try:
            import moonshine_onnx  # noqa: PLC0415
        except ImportError as e:
            raise InferenceError(
                "moonshine_onnx import failed at transcribe time",
                details={"provider": self.name, "error": str(e)},
            ) from e

        # Moonshine 推理：传 audio_path + model_name；max_tokens_per_second 是关键
        # 字段（中文/日文需调大），库 1+ 版本接受 kwarg 透传
        try:
            extra_kwargs: dict[str, Any] = {}
            if max_tps > 0:
                extra_kwargs["max_tokens_per_second"] = max_tps
            result = moonshine_onnx.transcribe(
                audio_path, model_name, **extra_kwargs,
            )
        except TypeError:
            # 版本兼容：旧版不接受 max_tokens_per_second kwarg；丢弃重试
            try:
                result = moonshine_onnx.transcribe(audio_path, model_name)
            except Exception as e:  # noqa: BLE001
                raise InferenceError(
                    f"Moonshine transcription failed: {e}",
                    details={"provider": self.name, "audio": audio_path},
                ) from e
        except Exception as e:  # noqa: BLE001
            raise InferenceError(
                f"Moonshine transcription failed: {e}",
                details={"provider": self.name, "audio": audio_path},
            ) from e

        # result 是 list[str]（多句串联）或 str（单句）；统一成单段长文本
        if isinstance(result, str):
            text = result
        elif isinstance(result, (list, tuple)):
            text = " ".join(str(x).strip() for x in result if x).strip()
        else:
            text = str(result).strip()

        duration = _audio_duration_seconds(audio_path)
        # Moonshine 不返回 segment 级时间戳：把整段输出装成单 segment [0, duration]
        # 满足 AsrResult 契约。这是上游能力限制，video_translate 字幕对齐若需细
        # 粒度时间戳应改用 WhisperProvider。
        segment = AsrSegment(start=0.0, end=duration, text=text)

        if progress_cb is not None:
            try:
                progress_cb(1.0)
            except Exception:  # noqa: BLE001
                pass

        return AsrResult(
            segments=[segment],
            language=(language or self.config.get("language") or "en"),
            duration=duration,
        )
