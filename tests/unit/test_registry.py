"""Provider 注册表契约。Mock 类通过 monkeypatch 临时注入。"""
from __future__ import annotations

import pytest

from voxcraft.errors import ProviderError
from voxcraft.providers import registry
from voxcraft.providers.mock import InMemoryMockAsrProvider


@pytest.fixture
def mock_registered(monkeypatch):
    monkeypatch.setitem(
        registry.PROVIDER_REGISTRY,
        "InMemoryMockAsrProvider",
        InMemoryMockAsrProvider,
    )


def test_resolve_known_class(mock_registered):
    cls = registry.resolve("InMemoryMockAsrProvider")
    assert cls is InMemoryMockAsrProvider


def test_resolve_unknown_raises_provider_error():
    with pytest.raises(ProviderError) as exc:
        registry.resolve("NonExistentProvider")
    assert exc.value.code == "PROVIDER_UNKNOWN"


def test_instantiate_returns_bound_instance(mock_registered):
    p = registry.instantiate(
        "InMemoryMockAsrProvider",
        name="my-asr",
        config={"foo": "bar"},
    )
    assert isinstance(p, InMemoryMockAsrProvider)
    assert p.name == "my-asr"
    assert p.config == {"foo": "bar"}


def test_instantiate_unknown_raises():
    with pytest.raises(ProviderError) as exc:
        registry.instantiate("Nope", name="x", config={})
    assert exc.value.code == "PROVIDER_UNKNOWN"
