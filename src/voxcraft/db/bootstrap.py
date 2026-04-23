"""启动时默认数据初始化 + 模型目录扫描。幂等。"""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import Engine
from sqlmodel import Session, select

from voxcraft.config import get_settings
from voxcraft.db.models import Model, Provider


def _build_defaults() -> list[Provider]:
    models_dir = str(get_settings().models_dir)
    return [
        Provider(
            kind="asr",
            name="whisper-medium-int8",
            class_name="WhisperProvider",
            config={
                "model_path": f"{models_dir}/whisper-medium",
                "compute_type": "int8",
                "device": "auto",
            },
            is_default=True,
        ),
        Provider(
            kind="tts",
            name="piper-zh",
            class_name="PiperProvider",
            config={
                "model": f"{models_dir}/piper/zh_CN-huayan-medium.onnx",
            },
            is_default=True,
        ),
        Provider(
            kind="cloning",
            name="voxcpm-clone",
            class_name="VoxCpmCloningProvider",
            config={
                "model_dir": f"{models_dir}/voxcpm",
                "device": "auto",
            },
            is_default=True,
        ),
        Provider(
            kind="separator",
            name="demucs-htdemucs",
            class_name="DemucsProvider",
            config={
                "model_name": "htdemucs",
                "device": "auto",
            },
            is_default=True,
        ),
    ]


def seed_default_providers(engine: Engine) -> int:
    """首次启动插入默认 Provider；若表非空直接返回 0。"""
    with Session(engine) as session:
        if session.exec(select(Provider)).first() is not None:
            return 0
        defaults = _build_defaults()
        for p in defaults:
            session.add(p)
        session.commit()
        return len(defaults)


def _dir_size_bytes(path: Path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def scan_existing_models(engine: Engine) -> int:
    """扫描 MODELS_DIR，把已下载但 DB 无记录的子目录补成 `manual_*` Model 行。

    - 仅扫描一级子目录；文件忽略。
    - catalog_key = f"manual_{subdir.name}"，与内置 key 隔离。
    - kind 默认 `unknown`，UI 可后续让用户分类。
    - 幂等：已有 catalog_key 的目录跳过。

    返回新增行数。
    """
    models_dir = get_settings().models_dir
    if not models_dir.exists():
        return 0

    with Session(engine) as session:
        existing = {m.catalog_key for m in session.exec(select(Model)).all()}
        inserted = 0
        for subdir in sorted(models_dir.iterdir()):
            if not subdir.is_dir():
                continue
            key = f"manual_{subdir.name}"
            if key in existing:
                continue
            session.add(
                Model(
                    catalog_key=key,
                    source="manual",
                    repo_id="",
                    kind="unknown",
                    local_path=str(subdir),
                    status="ready",
                    progress=1.0,
                    size_bytes=_dir_size_bytes(subdir),
                )
            )
            inserted += 1
        session.commit()
    return inserted
