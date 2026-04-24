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


def test_scan_does_not_duplicate_catalog_downloads(engine, tmp_path):
    """回归：之前每个下载好的 catalog 模型都会被扫成 `manual_<name>` 孤儿。"""
    from voxcraft.db.bootstrap import scan_existing_models
    from voxcraft.db.models import Model

    models_dir = tmp_path / "models"
    models_dir.mkdir()
    (models_dir / "whisper-tiny").mkdir()
    (models_dir / "whisper-tiny" / "model.bin").write_bytes(b"x" * 50)

    # 模拟 ModelDownloadService 下载完成：已有一行 Model 认领了该目录
    with Session(engine) as s:
        s.add(
            Model(
                catalog_key="whisper-tiny",
                source="hf",
                repo_id="Systran/faster-whisper-tiny",
                kind="asr",
                local_path=str(models_dir / "whisper-tiny"),
                status="ready",
                progress=1.0,
                size_bytes=50,
            )
        )
        s.commit()

    inserted = scan_existing_models(engine)
    assert inserted == 0, "已被 catalog Model 认领的目录不该再生成 manual_*"

    with Session(engine) as s:
        keys = {r.catalog_key for r in s.exec(select(Model)).all()}
        assert keys == {"whisper-tiny"}, "不该出现 manual_whisper-tiny 孤儿"


def test_scan_mixes_claimed_and_unclaimed_dirs(engine, tmp_path):
    """一个目录被 catalog Model 认领，另一个未认领 → 只有未认领的成为 manual。"""
    from voxcraft.db.bootstrap import scan_existing_models
    from voxcraft.db.models import Model

    models_dir = tmp_path / "models"
    models_dir.mkdir()
    (models_dir / "whisper-tiny").mkdir()
    (models_dir / "whisper-tiny" / "a.bin").write_bytes(b"1")
    (models_dir / "some-custom-lora").mkdir()
    (models_dir / "some-custom-lora" / "b.bin").write_bytes(b"2")

    with Session(engine) as s:
        s.add(
            Model(
                catalog_key="whisper-tiny",
                source="hf", repo_id="x", kind="asr",
                local_path=str(models_dir / "whisper-tiny"),
                status="ready", progress=1.0,
            )
        )
        s.commit()

    inserted = scan_existing_models(engine)
    assert inserted == 1

    with Session(engine) as s:
        keys = {r.catalog_key for r in s.exec(select(Model)).all()}
        assert keys == {"whisper-tiny", "manual_some-custom-lora"}


def test_scan_purges_legacy_manual_duplicates(engine, tmp_path):
    """历史遗留：旧版 scan bug 已经把同目录插成两条（catalog + manual_）。
    新版 scan 启动时应清理掉 manual_ 那条。"""
    from voxcraft.db.bootstrap import scan_existing_models
    from voxcraft.db.models import Model

    models_dir = tmp_path / "models"
    models_dir.mkdir()
    (models_dir / "whisper-tiny").mkdir()
    (models_dir / "whisper-tiny" / "a.bin").write_bytes(b"x")

    with Session(engine) as s:
        s.add(
            Model(
                catalog_key="whisper-tiny",
                source="hf", repo_id="x", kind="asr",
                local_path=str(models_dir / "whisper-tiny"),
                status="ready", progress=1.0,
            )
        )
        s.add(
            Model(
                catalog_key="manual_whisper-tiny",
                source="manual", repo_id="", kind="unknown",
                local_path=str(models_dir / "whisper-tiny"),
                status="ready", progress=1.0,
            )
        )
        s.commit()

    scan_existing_models(engine)

    with Session(engine) as s:
        keys = {r.catalog_key for r in s.exec(select(Model)).all()}
        assert keys == {"whisper-tiny"}, "manual_* 重复应被一次性清理"


def test_scan_keeps_standalone_manual_rows(engine, tmp_path):
    """单独存在的 manual_* 记录（无同目录 catalog 对应）不该被误删。"""
    from voxcraft.db.bootstrap import scan_existing_models
    from voxcraft.db.models import Model

    models_dir = tmp_path / "models"
    models_dir.mkdir()
    (models_dir / "my-fork").mkdir()
    (models_dir / "my-fork" / "w.bin").write_bytes(b"y")

    with Session(engine) as s:
        s.add(
            Model(
                catalog_key="manual_my-fork",
                source="manual", repo_id="", kind="unknown",
                local_path=str(models_dir / "my-fork"),
                status="ready", progress=1.0,
            )
        )
        s.commit()

    scan_existing_models(engine)

    with Session(engine) as s:
        keys = {r.catalog_key for r in s.exec(select(Model)).all()}
        assert keys == {"manual_my-fork"}


def test_scan_tolerates_claimed_path_on_missing_disk(engine, tmp_path):
    """Model.local_path 指向不存在的目录时，不影响其他目录的扫描。"""
    from voxcraft.db.bootstrap import scan_existing_models
    from voxcraft.db.models import Model

    models_dir = tmp_path / "models"
    models_dir.mkdir()
    (models_dir / "real-dir").mkdir()
    (models_dir / "real-dir" / "f.bin").write_bytes(b"ok")

    with Session(engine) as s:
        s.add(
            Model(
                catalog_key="ghost",
                source="hf", repo_id="x", kind="asr",
                local_path=str(models_dir / "no-such-dir"),
                status="ready", progress=1.0,
            )
        )
        s.commit()

    inserted = scan_existing_models(engine)
    # real-dir 未被认领 → 1 条 manual
    assert inserted == 1
