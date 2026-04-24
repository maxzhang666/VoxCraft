"""Provider CAPABILITIES 声明 + /admin/providers/classes 响应（ADR-014）。"""
from __future__ import annotations

from voxcraft.providers import capabilities
from voxcraft.providers.asr.whisper import WhisperProvider
from voxcraft.providers.cloning.indextts import IndexTtsProvider
from voxcraft.providers.cloning.voxcpm import VoxCpmCloningProvider
from voxcraft.providers.separator.demucs import DemucsProvider
from voxcraft.providers.tts.piper import PiperProvider


def test_capability_constants():
    assert capabilities.CLONE == "clone"


def test_cloning_providers_declare_clone():
    assert capabilities.CLONE in VoxCpmCloningProvider.CAPABILITIES
    assert capabilities.CLONE in IndexTtsProvider.CAPABILITIES


def test_non_cloning_providers_empty():
    assert PiperProvider.CAPABILITIES == frozenset()
    assert WhisperProvider.CAPABILITIES == frozenset()
    assert DemucsProvider.CAPABILITIES == frozenset()


def test_classes_endpoint_exposes_capabilities(client):
    r = client.get("/api/admin/providers/classes")
    assert r.status_code == 200, r.text
    by_name = {c["class_name"]: c for c in r.json()}

    assert "VoxCpmCloningProvider" in by_name
    assert "clone" in by_name["VoxCpmCloningProvider"]["capabilities"]

    assert "IndexTtsProvider" in by_name
    assert "clone" in by_name["IndexTtsProvider"]["capabilities"]

    # 非克隆 Provider 的 capabilities 字段存在且为空 list
    assert by_name["PiperProvider"]["capabilities"] == []
    assert by_name["WhisperProvider"]["capabilities"] == []
    assert by_name["DemucsProvider"]["capabilities"] == []
