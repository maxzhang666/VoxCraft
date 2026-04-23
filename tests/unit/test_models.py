"""Schema 与 CRUD 烟雾测试（in-memory SQLite）。"""
from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, SQLModel, create_engine, select

from voxcraft.db.models import AppSetting, Job, LlmProvider, Model, Provider, VoiceRef


@pytest.fixture
def session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def test_provider_crud(session):
    p = Provider(
        kind="asr",
        name="whisper-test",
        class_name="WhisperProvider",
        config={"model": "medium", "compute_type": "int8"},
        is_default=True,
    )
    session.add(p)
    session.commit()
    found = session.exec(select(Provider).where(Provider.kind == "asr")).first()
    assert found is not None
    assert found.name == "whisper-test"
    assert found.config == {"model": "medium", "compute_type": "int8"}
    assert found.is_default is True


def test_provider_name_unique(session):
    session.add(Provider(kind="asr", name="dup", class_name="X"))
    session.commit()
    session.add(Provider(kind="tts", name="dup", class_name="Y"))
    with pytest.raises(IntegrityError):
        session.commit()


def test_llm_provider_crud(session):
    session.add(
        LlmProvider(
            name="openai",
            base_url="https://api.openai.com/v1",
            api_key="sk-test-1234",
            model="gpt-4o-mini",
        )
    )
    session.commit()
    found = session.exec(select(LlmProvider)).first()
    assert found.api_key == "sk-test-1234"


def test_job_lifecycle(session):
    job = Job(id="uuid-1", kind="asr", status="pending", request={"audio": "a.wav"})
    session.add(job)
    session.commit()

    job.status = "succeeded"
    job.result = {"text": "hello"}
    job.output_path = "/data/outputs/uuid-1.json"
    session.commit()

    found = session.get(Job, "uuid-1")
    assert found.status == "succeeded"
    assert found.result == {"text": "hello"}
    assert found.output_path == "/data/outputs/uuid-1.json"
    assert found.output_extras is None


def test_voice_ref_crud(session):
    session.add(
        VoiceRef(
            id="vx_abc",
            speaker_name="张三",
            reference_audio_path="/data/refs/abc.wav",
            provider_name="voxcpm-clone",
        )
    )
    session.commit()
    v = session.get(VoiceRef, "vx_abc")
    assert v is not None
    assert v.speaker_name == "张三"


def test_app_setting_json_value(session):
    session.add(AppSetting(key="job_timeout", value={"seconds": 600}))
    session.commit()
    assert session.get(AppSetting, "job_timeout").value == {"seconds": 600}


# ---------- Model 表 (v0.1.2) ----------


def test_model_crud(session):
    m = Model(
        catalog_key="whisper-tiny",
        source="hf",
        repo_id="Systran/faster-whisper-tiny",
        kind="asr",
        size_bytes=39 * 1024 * 1024,
    )
    session.add(m)
    session.commit()

    found = session.exec(select(Model).where(Model.catalog_key == "whisper-tiny")).first()
    assert found is not None
    assert found.repo_id == "Systran/faster-whisper-tiny"
    assert found.kind == "asr"
    assert found.status == "pending"
    assert found.progress == 0.0
    assert found.local_path is None
    assert found.error_code is None


def test_model_catalog_key_unique(session):
    session.add(Model(catalog_key="voxcpm", source="hf", repo_id="x", kind="cloning"))
    session.commit()
    session.add(Model(catalog_key="voxcpm", source="ms", repo_id="y", kind="cloning"))
    with pytest.raises(IntegrityError):
        session.commit()


def test_model_lifecycle(session):
    m = Model(catalog_key="demucs", source="url", repo_id="htdemucs", kind="separator")
    session.add(m)
    session.commit()

    # pending -> downloading
    m.status = "downloading"
    m.progress = 0.42
    session.commit()

    # downloading -> ready
    m.status = "ready"
    m.progress = 1.0
    m.local_path = "/models/demucs"
    m.size_bytes = 300_000_000
    session.commit()

    refetched = session.exec(select(Model).where(Model.catalog_key == "demucs")).first()
    assert refetched.status == "ready"
    assert refetched.local_path == "/models/demucs"
    assert refetched.size_bytes == 300_000_000


def test_model_failure_state(session):
    m = Model(
        catalog_key="bad-model",
        source="hf",
        repo_id="nonexistent/repo",
        kind="asr",
        status="failed",
        error_code="DOWNLOAD_FAILED",
        error_message="404 Not Found",
    )
    session.add(m)
    session.commit()
    row = session.get(Model, m.id)
    assert row.status == "failed"
    assert row.error_code == "DOWNLOAD_FAILED"
