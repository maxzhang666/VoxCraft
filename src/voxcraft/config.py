"""启动参数（环境变量）。业务配置入 SQLite，见 db-schema.md。"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="VOXCRAFT_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    port: int = 8001
    log_level: str = "INFO"
    db: Path = Path("./data/voxcraft.sqlite")
    output_dir: Path = Path("./data/outputs")
    models_dir: Path = Path("./models")
    preferred_source: str = "hf"  # hf / ms — 国内用户建议改 ms
    # ADR-013 预留扩展点：inprocess=当前单进程调度；pool=worker 子进程，支持真取消
    scheduler_backend: Literal["inprocess", "pool"] = "inprocess"
    # /video-translate 上传大小上限（字节）。默认 2 GiB。ADR-014 §2。
    max_upload_size: int = 2 * 1024**3


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
