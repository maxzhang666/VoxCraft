"""内置模型 Catalog（v0.1.2 / ADR-010）。

每条 CatalogEntry 描述一个可下载的模型；用户自定义模型以 `custom_` 前缀区分，
扫描已下载目录补回的记录以 `manual_` 前缀。两个前缀为保留前缀，禁止内置 key 使用。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


Kind = Literal["asr", "tts", "cloning", "separator"]
Tier = Literal["entry", "mid", "high"]
MirrorAuthority = Literal["official", "community"]

# 禁止用户自定义 key / 内置 key 使用的前缀
RESERVED_PREFIXES: tuple[str, ...] = ("custom_", "manual_")


@dataclass(frozen=True)
class CatalogEntry:
    key: str
    label: str
    kind: Kind
    sources: dict[str, str]             # {"hf": "<repo>", "ms": "<repo>", "url": "<url>"}
    size_mb: int
    recommend_tier: Tier
    provider_class: str                  # 对应的 Provider 实现类（用户 UI 选模型即自动填）
    mirror_authority: MirrorAuthority = "official"


CATALOG: list[CatalogEntry] = [
    # ---------- ASR ----------
    CatalogEntry(
        key="whisper-tiny",
        label="Whisper Tiny",
        kind="asr",
        sources={
            "hf": "Systran/faster-whisper-tiny",
            "ms": "pengzhendong/faster-whisper-tiny",
        },
        size_mb=39,
        recommend_tier="entry",
        provider_class="WhisperProvider",
        mirror_authority="community",
    ),
    CatalogEntry(
        key="whisper-small",
        label="Whisper Small",
        kind="asr",
        sources={
            "hf": "Systran/faster-whisper-small",
            "ms": "pengzhendong/faster-whisper-small",
        },
        size_mb=244,
        recommend_tier="entry",
        provider_class="WhisperProvider",
        mirror_authority="community",
    ),
    CatalogEntry(
        key="whisper-medium",
        label="Whisper Medium",
        kind="asr",
        sources={
            "hf": "Systran/faster-whisper-medium",
            "ms": "pengzhendong/faster-whisper-medium",
        },
        size_mb=769,
        recommend_tier="mid",
        provider_class="WhisperProvider",
        mirror_authority="community",
    ),
    CatalogEntry(
        key="whisper-large-v3",
        label="Whisper Large v3",
        kind="asr",
        sources={
            "hf": "Systran/faster-whisper-large-v3",
            "ms": "keepitsimple/faster-whisper-large-v3",
        },
        size_mb=1500,
        recommend_tier="high",
        provider_class="WhisperProvider",
        mirror_authority="community",
    ),
    # ---------- TTS (Piper) ----------
    CatalogEntry(
        key="piper-zh-huayan-medium",
        label="Piper 中文 · 华艳 Medium",
        kind="tts",
        sources={
            "url": (
                "https://huggingface.co/rhasspy/piper-voices/resolve/main/"
                "zh/zh_CN/huayan/medium/zh_CN-huayan-medium.onnx"
            ),
        },
        size_mb=60,
        recommend_tier="entry",
        provider_class="PiperProvider",
        mirror_authority="official",
    ),
    CatalogEntry(
        key="piper-en-lessac-medium",
        label="Piper English · Lessac Medium",
        kind="tts",
        sources={
            "url": (
                "https://huggingface.co/rhasspy/piper-voices/resolve/main/"
                "en/en_US/lessac/medium/en_US-lessac-medium.onnx"
            ),
        },
        size_mb=60,
        recommend_tier="entry",
        provider_class="PiperProvider",
        mirror_authority="official",
    ),
    # ---------- Cloning ----------
    CatalogEntry(
        key="voxcpm-0.5b",
        label="VoxCPM 0.5B (Apache 2.0)",
        kind="cloning",
        sources={
            "hf": "openbmb/VoxCPM-0.5B",
            "ms": "OpenBMB/VoxCPM-0.5B",
        },
        size_mb=1024,
        recommend_tier="mid",
        provider_class="VoxCpmCloningProvider",
        mirror_authority="official",
    ),
    CatalogEntry(
        key="voxcpm-2",
        label="VoxCPM 2 (2B, Apache 2.0)",
        kind="cloning",
        sources={
            "hf": "openbmb/VoxCPM2",
            "ms": "OpenBMB/VoxCPM2",
        },
        size_mb=4096,
        recommend_tier="high",
        provider_class="VoxCpmCloningProvider",
        mirror_authority="official",
    ),
    CatalogEntry(
        key="indextts-1.5",
        label="IndexTTS 1.5 (非商业)",
        kind="cloning",
        sources={
            "hf": "IndexTeam/Index-TTS",
            "ms": "IndexTeam/IndexTTS-1.5",
        },
        size_mb=1500,
        recommend_tier="mid",
        provider_class="IndexTtsProvider",
        mirror_authority="official",
    ),
    CatalogEntry(
        key="indextts-2",
        label="IndexTTS 2 (非商业)",
        kind="cloning",
        sources={
            "hf": "IndexTeam/IndexTTS-2",
            "ms": "IndexTeam/IndexTTS-2",
        },
        size_mb=2048,
        recommend_tier="high",
        provider_class="IndexTtsProvider",
        mirror_authority="official",
    ),
    # ---------- Separator ----------
    CatalogEntry(
        key="demucs-htdemucs",
        label="Demucs htdemucs",
        kind="separator",
        sources={"url": "torch.hub://htdemucs"},  # Downloader 特殊分支
        size_mb=300,
        recommend_tier="mid",
        provider_class="DemucsProvider",
        mirror_authority="official",
    ),
]


# --- 启动时自检，避免脏清单 ---

def _validate_catalog() -> None:
    keys: set[str] = set()
    for e in CATALOG:
        if any(e.key.startswith(p) for p in RESERVED_PREFIXES):
            raise ValueError(f"Catalog key uses reserved prefix: {e.key}")
        if e.key in keys:
            raise ValueError(f"Duplicate catalog key: {e.key}")
        if not e.sources:
            raise ValueError(f"Catalog {e.key} has no sources")
        keys.add(e.key)


_validate_catalog()


# --- 公共 API ---

def get_by_key(key: str) -> CatalogEntry | None:
    for e in CATALOG:
        if e.key == key:
            return e
    return None


def is_reserved_key(key: str) -> bool:
    """用户自定义添加时校验：是否冲突到保留前缀或内置 key。"""
    if any(key.startswith(p) for p in RESERVED_PREFIXES):
        return True
    return any(e.key == key for e in CATALOG)
