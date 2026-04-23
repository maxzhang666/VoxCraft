"""LlmClient 单元测试（v0.3.0）。mock openai SDK，不发真实 HTTP。"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlmodel import Session, SQLModel, create_engine

from voxcraft.db.models import LlmProvider
from voxcraft.errors import LlmApiError, LlmNotConfiguredError
from voxcraft.llm.client import LlmClient, redact_sk


@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


class _StubChatCompletions:
    """OpenAI SDK chat.completions.create 的 mock。"""

    def __init__(self, text: str = "hello", raise_exc: Exception | None = None):
        self.last_kwargs: dict = {}
        self._text = text
        self._raise = raise_exc

    def create(self, **kwargs):
        self.last_kwargs = kwargs
        if self._raise is not None:
            raise self._raise
        msg = SimpleNamespace(content=self._text)
        choice = SimpleNamespace(message=msg)
        return SimpleNamespace(choices=[choice])


class _StubOpenAI:
    def __init__(self, stub: _StubChatCompletions):
        self.chat = SimpleNamespace(completions=stub)


def _patch_openai(monkeypatch, stub: _StubChatCompletions) -> None:
    from voxcraft.llm import client as client_mod

    def factory(base_url, api_key, timeout):  # noqa: ARG001
        return _StubOpenAI(stub)

    monkeypatch.setattr(client_mod, "OpenAI", factory, raising=False)
    # _ensure_client 里 `from openai import OpenAI`——替换该模块里的 OpenAI 即可
    import openai
    monkeypatch.setattr(openai, "OpenAI", factory)


def test_chat_calls_openai_and_returns_content(monkeypatch):
    stub = _StubChatCompletions(text="你好，世界")
    _patch_openai(monkeypatch, stub)

    c = LlmClient(base_url="http://x", api_key="sk-test", model="gpt-4o-mini")
    r = c.chat([{"role": "user", "content": "hi"}], temperature=0.2)
    assert r == "你好，世界"
    assert stub.last_kwargs["model"] == "gpt-4o-mini"
    assert stub.last_kwargs["messages"][0]["content"] == "hi"
    assert stub.last_kwargs["temperature"] == 0.2


def test_chat_model_override(monkeypatch):
    stub = _StubChatCompletions()
    _patch_openai(monkeypatch, stub)
    c = LlmClient(base_url="http://x", api_key="sk", model="default-m")
    c.chat([{"role": "user", "content": "hi"}], model="override-m")
    assert stub.last_kwargs["model"] == "override-m"


def test_chat_wraps_exception_as_llm_api_error(monkeypatch):
    stub = _StubChatCompletions(raise_exc=RuntimeError("boom sk-leaked-abcdef"))
    _patch_openai(monkeypatch, stub)
    c = LlmClient(base_url="http://x", api_key="sk", model="m")
    with pytest.raises(LlmApiError) as ei:
        c.chat([{"role": "user", "content": "hi"}])
    # sk-* redact 生效
    assert "sk-leaked" not in str(ei.value.message)
    assert "REDACTED" in str(ei.value.message)


def test_from_db_picks_default(session):
    session.add(
        LlmProvider(
            name="openai", base_url="http://a", api_key="sk-a",
            model="m1", is_default=True,
        )
    )
    session.add(
        LlmProvider(
            name="deepseek", base_url="http://b", api_key="sk-b",
            model="m2", is_default=False,
        )
    )
    session.commit()
    c = LlmClient.from_db(session)
    assert c.default_model == "m1"
    assert c.base_url == "http://a"


def test_from_db_by_name(session):
    session.add(
        LlmProvider(
            name="deepseek", base_url="http://b", api_key="sk-b",
            model="m2", is_default=False,
        )
    )
    session.commit()
    c = LlmClient.from_db(session, name="deepseek")
    assert c.default_model == "m2"


def test_from_db_disabled_raises(session):
    session.add(
        LlmProvider(
            name="x", base_url="http://x", api_key="sk", model="m",
            is_default=True, enabled=False,
        )
    )
    session.commit()
    with pytest.raises(LlmNotConfiguredError):
        LlmClient.from_db(session)


def test_from_db_missing_raises(session):
    with pytest.raises(LlmNotConfiguredError):
        LlmClient.from_db(session)
    with pytest.raises(LlmNotConfiguredError):
        LlmClient.from_db(session, name="ghost")


def test_redact_sk_helper():
    s = "got key sk-1234567890abcdef and sk-ABCDEF_test-2"
    out = redact_sk(s)
    assert "sk-1234567890abcdef" not in out
    assert "sk-ABCDEF_test-2" not in out
    assert out.count("REDACTED") == 2
