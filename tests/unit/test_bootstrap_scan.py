"""bootstrap.scan_existing_models 扫描 MODELS_DIR 补 manual Model 行（v0.1.2）。"""
from __future__ import annotations

import pytest
from sqlmodel import Session, SQLModel, select


@pytest.fixture
def engine(tmp_path, monkeypatch):
    """独立 DB + 独立 MODELS_DIR 的隔离 fixture。"""
    monkeypatch.setenv("VOXCRAFT_DB", str(tmp_path / "scan.sqlite"))
    monkeypatch.setenv("VOXCRAFT_OUTPUT_DIR", str(tmp_path / "outputs"))
    monkeypatch.setenv("VOXCRAFT_MODELS_DIR", str(tmp_path / "models"))
    from voxcraft.config import get_settings
    from voxcraft.db.engine import get_engine

    get_settings.cache_clear()
    get_engine.cache_clear()
    eng = get_engine()
    SQLModel.metadata.create_all(eng)
    yield eng
    get_settings.cache_clear()
    get_engine.cache_clear()


def test_scan_empty_models_dir_returns_zero(engine, tmp_path):
    from voxcraft.db.bootstrap import scan_existing_models

    # MODELS_DIR 不存在或为空
    assert scan_existing_models(engine) == 0


def test_scan_adds_manual_rows_for_new_dirs(engine, tmp_path):
    from voxcraft.db.bootstrap import scan_existing_models
    from voxcraft.db.models import Model

    models_dir = tmp_path / "models"
    models_dir.mkdir()
    (models_dir / "whisper-tiny").mkdir()
    (models_dir / "whisper-tiny" / "model.bin").write_bytes(b"x" * 100)
    (models_dir / "piper-zh").mkdir()
    (models_dir / "piper-zh" / "voice.onnx").write_bytes(b"y" * 200)

    inserted = scan_existing_models(engine)
    assert inserted == 2

    with Session(engine) as s:
        rows = s.exec(select(Model)).all()
        keys = {r.catalog_key for r in rows}
        assert keys == {"manual_whisper-tiny", "manual_piper-zh"}
        for r in rows:
            assert r.source == "manual"
            assert r.status == "ready"
            assert r.progress == 1.0
            assert r.size_bytes and r.size_bytes > 0


def test_scan_is_idempotent(engine, tmp_path):
    from voxcraft.db.bootstrap import scan_existing_models

    models_dir = tmp_path / "models"
    models_dir.mkdir()
    (models_dir / "voxcpm").mkdir()
    (models_dir / "voxcpm" / "config.json").write_text("{}")

    first = scan_existing_models(engine)
    second = scan_existing_models(engine)
    assert first == 1
    assert second == 0


def test_scan_skips_files_only_processes_dirs(engine, tmp_path):
    from voxcraft.db.bootstrap import scan_existing_models

    models_dir = tmp_path / "models"
    models_dir.mkdir()
    (models_dir / "stray.txt").write_text("noise")
    (models_dir / "whisper-medium").mkdir()
    (models_dir / "whisper-medium" / "model.bin").write_bytes(b"z")

    assert scan_existing_models(engine) == 1
