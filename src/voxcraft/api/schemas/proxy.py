"""代理配置 schema。"""
from __future__ import annotations

from pydantic import BaseModel, Field


class ProxySettings(BaseModel):
    hf_endpoint: str = Field(default="", description="HuggingFace 镜像地址")
    https_proxy: str = Field(default="")
    http_proxy: str = Field(default="")
    no_proxy: str = Field(default="")
