"""Provider 抽象基类与结果类型。契约依 architecture/providers.md。"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, ClassVar, Literal


ConfigFieldType = Literal["path", "enum", "str", "int", "bool"]


@dataclass(frozen=True)
class ConfigField:
    """Provider 配置字段的声明，用于驱动前端动态表单。

    - path：视为字符串；前端一般只读（来自模型库）
    - enum：必须同时提供 `options`
    - str/int/bool：普通标量
    """

    key: str
    label: str
    type: ConfigFieldType
    required: bool = False
    default: Any = None
    options: tuple[str, ...] | None = None
    help: str | None = None


@dataclass
class ProviderInfo:
    kind: str
    name: str
    class_name: str
    loaded: bool
    languages: list[str] | None = None
    vram_mb: int | None = None
    extra: dict | None = None


@dataclass
class AsrSegment:
    start: float
    end: float
    text: str


@dataclass
class AsrResult:
    segments: list[AsrSegment]
    language: str
    duration: float


@dataclass
class Voice:
    id: str
    language: str
    gender: str | None = None
    sample_url: str | None = None


@dataclass
class SeparateResult:
    vocals_path: str
    instrumental_path: str


class Provider(ABC):
    """所有 Provider 的共同基类。子类必须声明 kind。"""

    kind: ClassVar[str]
    # 面向最终用户的可读名；默认用类名，子类可覆盖
    LABEL: ClassVar[str] = ""
    # 驱动前端动态表单的 config 字段声明
    CONFIG_SCHEMA: ClassVar[list[ConfigField]] = []
    # 能力声明（ADR-014）。常量见 voxcraft.providers.capabilities。
    # 供编排层前置验证（如 /video-translate 检查 TTS 是否支持 "clone"）。
    CAPABILITIES: ClassVar[frozenset[str]] = frozenset()

    def __init__(self, name: str, config: dict) -> None:
        self.name = name
        self.config = config
        self._loaded = False

    @abstractmethod
    def load(self) -> None:
        """加载模型到 GPU/内存。幂等。"""

    @abstractmethod
    def unload(self) -> None:
        """卸载模型，释放资源。幂等。"""

    @abstractmethod
    def info(self) -> ProviderInfo: ...

    @property
    def loaded(self) -> bool:
        return self._loaded


class AsrProvider(Provider):
    kind: ClassVar[str] = "asr"

    @abstractmethod
    def transcribe(
        self,
        audio_path: str,
        language: str | None = None,
        progress_cb: "Callable[[float], None] | None" = None,
        options: dict | None = None,
    ) -> AsrResult:
        """`progress_cb(p)` 接受 0.0~1.0 的浮点数；实现方自行决定汇报节奏。

        ``options`` 是后端无关的调优参数键值对，由路由层从用户请求收集。
        当前 Whisper 支持的 keys（faster-whisper 命名）：
        beam_size / initial_prompt / temperature / condition_on_previous_text /
        compression_ratio_threshold / log_prob_threshold / no_speech_threshold /
        vad_filter / word_timestamps。Provider 缺省值 + 请求 override 由实现合并。
        """
        ...


class TtsProvider(Provider):
    kind: ClassVar[str] = "tts"

    def __init__(self, name: str, config: dict) -> None:
        super().__init__(name, config)
        # 最近一次 synthesize 的可观测元数据：resolved 后的实际输入（含来源归属）+
        # 参考音频时长 + 输出音频时长 + sample rate 等。Provider 实现按需填，
        # worker 读出后合入 JobResult.result["synthesis_debug"]，前端任务详情直接展示。
        # 不填即 None；老 Provider 不破坏。
        self.last_synthesis_debug: dict | None = None

    @abstractmethod
    def synthesize(
        self,
        text: str,
        voice_id: str,
        speed: float = 1.0,
        format: str = "wav",
        reference_audio_path: str | None = None,
        voice_metadata: dict | None = None,
        generation_params: dict | None = None,
    ) -> bytes:
        """返回合成后的音频字节。

        ``reference_audio_path``：可选参考声纹路径——zero-shot 克隆模型
        （VoxCPM / GPT-SoVITS / IndexTTS）需要做 speaker embedding；预设音色
        Provider（Piper）忽略。worker 根据 voice_id 反查 voice_refs.reference_audio_path。

        ``voice_metadata``：voice 粒度元数据（worker 反查 voice_refs 注入）。
        当前已知字段：
          - prompt_text（参考音频转写）：GPT-SoVITS / VoxCPM 1.x 强制；
            VoxCPM 2 可选（启用时升级到 ultimate cloning）
          - prompt_lang（参考音频语言代码）：GPT-SoVITS 跨语种克隆必需
          - speaker_name：用户标注，仅展示
        Provider 应优先读 voice_metadata，找不到才 fallback 到 self.config 默认值。

        ``generation_params``：本次生成的采样/切分覆盖（来自 TTS 请求 body.generation）。
        当前已知字段：top_k / top_p / temperature / text_split_method（GPT-SoVITS）/
        cfg_value / inference_timesteps（VoxCPM）。Provider 优先读 generation_params，
        找不到才 fallback 到 self.config 默认值；不识别的字段忽略。
        """
        ...

    @abstractmethod
    def list_voices(self) -> list[Voice]: ...


class CloningProvider(TtsProvider):
    kind: ClassVar[str] = "cloning"

    @abstractmethod
    def clone_voice(
        self,
        reference_audio_path: str,
        speaker_name: str | None = None,
    ) -> str:
        """返回 voice_id，可在 synthesize() 中复用。"""


class SeparatorProvider(Provider):
    kind: ClassVar[str] = "separator"

    @abstractmethod
    def separate(self, audio_path: str) -> SeparateResult: ...


class TranslationProvider(Provider):
    kind: ClassVar[str] = "translation"

    @abstractmethod
    async def translate(
        self,
        text: str,
        source_lang: str | None,
        target_lang: str,
    ) -> str: ...
