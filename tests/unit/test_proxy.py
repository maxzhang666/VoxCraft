"""代理配置：DB 读写 + env 注入。"""
from __future__ import annotations

import os

import pytest
from sqlmodel import Session, SQLModel, create_engine

from voxcraft.db.models import AppSetting
from voxcraft.runtime.proxy import (
    apply_proxy_to_env,
    load_proxy_settings,
    reload_proxy_from_db,
    save_proxy_settings,
)


@pytest.fixture
def engine(tmp_path):
    eng = create_engine(f"sqlite:///{tmp_path / 'test.sqlite'}")
    SQLModel.metadata.create_all(eng)
    return eng


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    # 隔离 env，避免互相污染
    for k in ("HF_ENDPOINT", "HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY"):
        monkeypatch.delenv(k, raising=False)
    yield


def test_load_returns_empty_when_no_record(engine):
    assert load_proxy_settings(engine) == {}


def test_save_and_reload_roundtrip(engine):
    saved = save_proxy_settings(engine, {
        "hf_endpoint": "https://hf-mirror.com",
        "https_proxy": "http://10.0.0.1:7890",
    })
    assert saved["hf_endpoint"] == "https://hf-mirror.com"
    assert saved["http_proxy"] == ""  # 缺失字段补空串

    loaded = load_proxy_settings(engine)
    assert loaded["hf_endpoint"] == "https://hf-mirror.com"
    assert loaded["https_proxy"] == "http://10.0.0.1:7890"


def test_apply_writes_env():
    apply_proxy_to_env({
        "hf_endpoint": "https://hf-mirror.com",
        "https_proxy": "http://proxy:7890",
        "http_proxy": "",
        "no_proxy": "localhost",
    })
    assert os.environ["HF_ENDPOINT"] == "https://hf-mirror.com"
    assert os.environ["HTTPS_PROXY"] == "http://proxy:7890"
    assert "HTTP_PROXY" not in os.environ  # 空值不污染
    assert os.environ["NO_PROXY"] == "localhost"


def test_apply_clears_when_empty(monkeypatch):
    monkeypatch.setenv("HF_ENDPOINT", "stale-value")
    apply_proxy_to_env({"hf_endpoint": ""})
    assert "HF_ENDPOINT" not in os.environ


def test_save_filters_unknown_keys(engine):
    saved = save_proxy_settings(engine, {
        "hf_endpoint": "https://x",
        "evil_field": "ignored",
    })
    assert "evil_field" not in saved
    assert saved["hf_endpoint"] == "https://x"


def test_reload_combines_load_and_apply(engine):
    save_proxy_settings(engine, {"hf_endpoint": "https://hf-mirror.com"})
    active = reload_proxy_from_db(engine)
    assert active["hf_endpoint"] == "https://hf-mirror.com"
    assert os.environ["HF_ENDPOINT"] == "https://hf-mirror.com"
