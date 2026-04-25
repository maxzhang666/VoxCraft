"""/admin/settings/* —— 应用级 key-value 配置（代理等）。"""
from __future__ import annotations

from fastapi import APIRouter

from voxcraft.api.schemas.proxy import ProxySettings
from voxcraft.db.engine import get_engine
from voxcraft.runtime.proxy import (
    apply_proxy_to_env,
    load_proxy_settings,
    save_proxy_settings,
)


router = APIRouter(prefix="/admin/settings", tags=["admin"])


@router.get("/proxy", response_model=ProxySettings)
def get_proxy() -> ProxySettings:
    """返回当前 DB 中的代理配置。前端展示 / 编辑用。"""
    return ProxySettings(**load_proxy_settings(get_engine()))


@router.put("/proxy", response_model=ProxySettings)
def update_proxy(payload: ProxySettings) -> ProxySettings:
    """保存代理配置并立即注入 os.environ；后续 huggingface_hub / httpx 即生效。"""
    saved = save_proxy_settings(get_engine(), payload.model_dump())
    apply_proxy_to_env(saved)
    return ProxySettings(**saved)
