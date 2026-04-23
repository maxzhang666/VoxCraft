"""启动参数（环境变量）。业务配置入 SQLite，见 db-schema.md。"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

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


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
