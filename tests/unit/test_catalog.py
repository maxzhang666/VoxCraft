"""Catalog 模块契约（v0.1.2 / ADR-010）。"""
from __future__ import annotations

import pytest

from voxcraft.models_lib.catalog import (
    CATALOG,
    RESERVED_PREFIXES,
    CatalogEntry,
    get_by_key,
    is_reserved_key,
)


def test_catalog_has_twelve_entries():
    assert len(CATALOG) == 12


def test_catalog_keys_unique():
    keys = [e.key for e in CATALOG]
    assert len(keys) == len(set(keys)), "duplicate catalog keys"


def test_catalog_no_reserved_prefix():
    for e in CATALOG:
        assert not any(e.key.startswith(p) for p in RESERVED_PREFIXES)


def test_catalog_kinds_valid():
    allowed = {"asr", "tts", "cloning", "separator"}
    for e in CATALOG:
        assert e.kind in allowed


def test_catalog_every_entry_has_sources():
    for e in CATALOG:
        assert e.sources, f"{e.key} has no sources"


def test_get_by_key_hit_and_miss():
    assert get_by_key("whisper-tiny") is not None
    assert get_by_key("nonexistent-model") is None


def test_is_reserved_key():
    # 内置 key 视为保留
    assert is_reserved_key("whisper-tiny") is True
    # 保留前缀
    assert is_reserved_key("custom_my-model") is True
    assert is_reserved_key("manual_xyz") is True
    # 合法自定义（用户应加 custom_ 前缀，这里故意未加 → 不是保留）
    assert is_reserved_key("my-brand-new-model") is False


def test_catalog_entry_is_frozen():
    e = CATALOG[0]
    with pytest.raises(Exception):  # FrozenInstanceError from dataclass(frozen=True)
        e.key = "mutated"  # type: ignore[misc]


def test_catalog_cloning_entries_include_known_providers():
    cloning_keys = {e.key for e in CATALOG if e.kind == "cloning"}
    assert "voxcpm-0.5b" in cloning_keys
    assert "voxcpm-2" in cloning_keys
    assert "indextts-1.5" in cloning_keys
    assert "indextts-2" in cloning_keys
    assert "gpt-sovits-v2pro" in cloning_keys


def test_ms_sources_for_cn_users():
    """国内用户依赖 ModelScope 镜像，至少 Whisper/VoxCPM/IndexTTS 要有 ms 源。"""
    for e in CATALOG:
        if e.kind in ("asr", "cloning"):
            assert "ms" in e.sources or "url" in e.sources, f"{e.key} lacks CN-friendly source"
