"""bootstrap 默认 Provider 种子逻辑。"""
from __future__ import annotations

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from voxcraft.db.bootstrap import seed_default_providers
from voxcraft.db.models import Provider


@pytest.fixture
def engine():
    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    SQLModel.metadata.create_all(eng)
    return eng


def test_seed_inserts_four_defaults_on_empty_db(engine):
    count = seed_default_providers(engine)
    assert count == 4

    with Session(engine) as s:
        rows = s.exec(select(Provider)).all()
        assert len(rows) == 4
        assert {r.kind for r in rows} == {"asr", "tts", "cloning", "separator"}
        assert all(r.is_default for r in rows)
        assert all(r.enabled for r in rows)


def test_seed_is_idempotent(engine):
    assert seed_default_providers(engine) == 4
    assert seed_default_providers(engine) == 0
    with Session(engine) as s:
        assert len(s.exec(select(Provider)).all()) == 4


def test_seed_sets_expected_class_names(engine):
    seed_default_providers(engine)
    with Session(engine) as s:
        by_kind = {r.kind: r for r in s.exec(select(Provider)).all()}
        assert by_kind["asr"].class_name == "WhisperProvider"
        assert by_kind["tts"].class_name == "PiperProvider"
        assert by_kind["cloning"].class_name == "VoxCpmCloningProvider"
        assert by_kind["separator"].class_name == "DemucsProvider"
