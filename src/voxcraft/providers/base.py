"""Provider 抽象基类与结果类型。契约依 architecture/providers.md。"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, ClassVar, Literal


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
        self, audio_path: str, language: str | None = None
    ) -> AsrResult: ...


class TtsProvider(Provider):
    kind: ClassVar[str] = "tts"

    @abstractmethod
    def synthesize(
        self,
        text: str,
        voice_id: str,
        speed: float = 1.0,
        format: str = "wav",
    ) -> bytes: ...

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
