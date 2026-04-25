"""Mock Provider 实现，仅供测试注入。不登记到 PROVIDER_REGISTRY。"""
from __future__ import annotations

import tempfile
import uuid
from pathlib import Path

from voxcraft.providers import capabilities
from voxcraft.providers.base import (
    AsrProvider,
    AsrResult,
    AsrSegment,
    CloningProvider,
    ProviderInfo,
    SeparateResult,
    SeparatorProvider,
    TtsProvider,
    Voice,
)


class InMemoryMockAsrProvider(AsrProvider):
    def load(self) -> None:
        self._loaded = True

    def unload(self) -> None:
        self._loaded = False

    def info(self) -> ProviderInfo:
        return ProviderInfo(
            kind="asr",
            name=self.name,
            class_name=type(self).__name__,
            loaded=self._loaded,
            languages=["zh", "en"],
            vram_mb=0,
        )

    def transcribe(
        self,
        audio_path: str,
        language: str | None = None,
        progress_cb=None,
        options: dict | None = None,  # noqa: ARG002 — mock 忽略调优参数
    ) -> AsrResult:
        if progress_cb is not None:
            progress_cb(0.5)
            progress_cb(1.0)
        return AsrResult(
            segments=[AsrSegment(start=0.0, end=1.0, text="mock text")],
            language=language or "zh",
            duration=1.0,
        )


class InMemoryMockTtsProvider(TtsProvider):
    def load(self) -> None:
        self._loaded = True

    def unload(self) -> None:
        self._loaded = False

    def info(self) -> ProviderInfo:
        return ProviderInfo(
            kind="tts", name=self.name, class_name=type(self).__name__,
            loaded=self._loaded, vram_mb=0,
        )

    def synthesize(
        self, text: str, voice_id: str, speed: float = 1.0, format: str = "wav",
    ) -> bytes:
        return b"RIFF....WAVEmock"

    def list_voices(self) -> list[Voice]:
        return [Voice(id="mock-voice", language="zh")]


class InMemoryMockSeparatorProvider(SeparatorProvider):
    def load(self) -> None:
        self._loaded = True

    def unload(self) -> None:
        self._loaded = False

    def info(self) -> ProviderInfo:
        return ProviderInfo(
            kind="separator", name=self.name, class_name=type(self).__name__,
            loaded=self._loaded, vram_mb=0,
        )

    def separate(self, audio_path: str) -> SeparateResult:
        tmp = Path(tempfile.gettempdir())
        suffix = uuid.uuid4().hex[:8]
        v = tmp / f"mock-vocals-{suffix}.wav"
        i = tmp / f"mock-instr-{suffix}.wav"
        v.write_bytes(b"RIFFmockvocalsdata")
        i.write_bytes(b"RIFFmockinstrudata")
        return SeparateResult(vocals_path=str(v), instrumental_path=str(i))


class InMemoryMockCloningProvider(CloningProvider):
    CAPABILITIES = frozenset({capabilities.CLONE})

    def __init__(self, name: str, config: dict) -> None:
        super().__init__(name, config)
        self._voices: dict[str, str] = {}  # voice_id → speaker_name

    def load(self) -> None:
        self._loaded = True

    def unload(self) -> None:
        self._loaded = False

    def info(self) -> ProviderInfo:
        return ProviderInfo(
            kind="cloning", name=self.name, class_name=type(self).__name__,
            loaded=self._loaded, vram_mb=0,
        )

    def synthesize(
        self, text: str, voice_id: str, speed: float = 1.0, format: str = "wav",
    ) -> bytes:
        return b"RIFFmockclonewave"

    def list_voices(self) -> list[Voice]:
        return [Voice(id=vid, language="zh") for vid in self._voices]

    def clone_voice(
        self, reference_audio_path: str, speaker_name: str | None = None,
    ) -> str:
        vid = f"vx_mock_{uuid.uuid4().hex[:10]}"
        self._voices[vid] = speaker_name or ""
        return vid
