"""模型下载代理：从 AppSetting (key=network_proxy) 读取并注入 os.environ。

支持 4 个环境变量（HuggingFace / requests / httpx 等都尊重）：
- HF_ENDPOINT  HuggingFace 镜像地址（如 https://hf-mirror.com）
- HTTPS_PROXY  通用 HTTPS 代理
- HTTP_PROXY   通用 HTTP 代理
- NO_PROXY     代理排除清单（逗号分隔）

时机：应用启动 lifespan 调用一次；每次模型下载前再调用一次（覆盖 UI 改动）。
"""
from __future__ import annotations

import os

from sqlmodel import Session

from voxcraft.db.models import AppSetting

PROXY_KEY = "network_proxy"

# 字段 → 环境变量；DB value 用 snake_case，env 用 UPPERCASE
_FIELD_ENV: dict[str, str] = {
    "hf_endpoint": "HF_ENDPOINT",
    "https_proxy": "HTTPS_PROXY",
    "http_proxy": "HTTP_PROXY",
    "no_proxy": "NO_PROXY",
}


def load_proxy_settings(engine) -> dict[str, str]:
    """从 DB 读代理配置；无记录返回空 dict。"""
    with Session(engine) as session:
        row = session.get(AppSetting, PROXY_KEY)
    if row is None or not isinstance(row.value, dict):
        return {}
    # 只保留约定字段，过滤未知 key 防御脏数据
    return {k: str(row.value.get(k, "")) for k in _FIELD_ENV}


def save_proxy_settings(engine, settings: dict[str, str]) -> dict[str, str]:
    """保存代理配置到 DB；返回保存后的全部字段（缺失补空串）。"""
    cleaned = {k: str(settings.get(k, "")).strip() for k in _FIELD_ENV}
    with Session(engine) as session:
        row = session.get(AppSetting, PROXY_KEY)
        if row is None:
            row = AppSetting(key=PROXY_KEY, value=cleaned)
            session.add(row)
        else:
            row.value = cleaned
        session.commit()
    return cleaned


def apply_proxy_to_env(settings: dict[str, str]) -> None:
    """把 settings 写到 os.environ；空值会清掉对应 env，不污染全局。"""
    for field, env_name in _FIELD_ENV.items():
        v = settings.get(field, "").strip()
        if v:
            os.environ[env_name] = v
        else:
            os.environ.pop(env_name, None)


def reload_proxy_from_db(engine) -> dict[str, str]:
    """组合操作：load + apply。返回当前生效的配置。"""
    settings = load_proxy_settings(engine)
    apply_proxy_to_env(settings)
    return settings
