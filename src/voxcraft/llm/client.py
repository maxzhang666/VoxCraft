"""OpenAI 兼容 LLM 客户端（v0.3.0 / plans/voxcraft-llm-integration）。

只支持 OpenAI `/v1/chat/completions` 协议族：OpenAI / DeepSeek / Qwen / Ollama (0.1.14+) 等。
不考虑 Anthropic 原生 Messages API 等非兼容协议。

消费者用法：
    from voxcraft.llm import LlmClient

    with Session(engine) as s:
        client = LlmClient.from_db(s)             # 默认 provider
        text = client.chat([{"role": "user", "content": "你好"}])

    # 或指名
    client = LlmClient.from_db(s, name="deepseek")
"""
from __future__ import annotations

import re
from typing import Any

from sqlmodel import Session, select

from voxcraft.db.models import LlmProvider
from voxcraft.errors import LlmApiError, LlmNotConfiguredError


# 日志 redact：匹配 OpenAI/DeepSeek/Qwen/Ollama 等主流 API Key 前缀
# 用于异常消息/日志处理；见 plans/voxcraft-llm-integration §风险
_SK_PATTERN = re.compile(r"sk-[A-Za-z0-9_\-]{6,}")


def redact_sk(text: str) -> str:
    """屏蔽字符串中的 sk-* API Key 前缀，供日志/异常消息使用。"""
    return _SK_PATTERN.sub("sk-***REDACTED***", text)


def _extract_model_ids(payload: Any) -> list[str]:
    """从各种 /models 响应格式里柔性抽出 id 字符串列表。"""
    out: list[str] = []
    if not isinstance(payload, dict):
        return out

    # 主流字段名候选
    items = payload.get("data") or payload.get("models") or []
    if not isinstance(items, list):
        return out

    for it in items:
        if isinstance(it, str):
            if it.strip():
                out.append(it.strip())
        elif isinstance(it, dict):
            # OpenAI 标准：id；部分兼容层：name / model
            for key in ("id", "name", "model"):
                v = it.get(key)
                if isinstance(v, str) and v.strip():
                    out.append(v.strip())
                    break
    return out


class LlmClient:
    """OpenAI 兼容 API 的同步客户端。

    - 构造：直接传 base_url / api_key / model
    - 工厂：`LlmClient.from_db(session, name=None)` 从 DB 加载配置
    - 核心：`chat(messages, model=None, **kw) -> str`
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        timeout: float = 30.0,
    ) -> None:
        self.base_url = base_url
        self.api_key = api_key
        self.default_model = model
        self.timeout = timeout
        self._client: Any | None = None  # 懒初始化 openai.OpenAI

    @classmethod
    def from_db(
        cls, session: Session, name: str | None = None,
    ) -> "LlmClient":
        """从 DB 加载 LLM Provider 配置。

        - name=None → 使用 `is_default=True` 的 Provider
        - name 指定 → 按名查
        - 缺失或禁用 → `LlmNotConfiguredError`
        """
        q = select(LlmProvider).where(LlmProvider.enabled == True)  # noqa: E712
        if name:
            q = q.where(LlmProvider.name == name)
        else:
            q = q.where(LlmProvider.is_default == True)  # noqa: E712
        row = session.exec(q).first()
        if row is None:
            raise LlmNotConfiguredError(
                f"No enabled LLM provider" + (f" named {name!r}" if name else " (no default)"),
                details={"requested": name},
            )
        return cls(
            base_url=row.base_url,
            api_key=row.api_key,
            model=row.model,
        )

    def _ensure_client(self) -> Any:
        if self._client is None:
            try:
                from openai import OpenAI
            except ImportError as e:
                raise LlmApiError(
                    "openai SDK not installed; add `openai` to dependencies",
                ) from e
            self._client = OpenAI(
                base_url=self.base_url,
                api_key=self.api_key,
                timeout=self.timeout,
            )
        return self._client

    def list_models(self) -> list[str]:
        """调用 OpenAI 兼容 `GET /v1/models`，返回模型 id 列表（已排序）。

        不用 openai SDK —— SDK 会用 Pydantic 严格反序列化，遇到 Ollama / vllm /
        部分 Azure 定制等返回非标准结构（如 data 是 string[] 而非 object[]）就报
        `'str' object has no attribute '_set_private_attributes'`。

        这里用 httpx 直 GET 然后柔性解析，兼容：
        - 标准：`{data: [{id: "..."}]}` （OpenAI）
        - 对象含 name 而非 id：`{data: [{name: "..."}]}` （部分兼容层）
        - 字符串列表：`{data: ["m1", "m2"]}` 或 `{models: ["m1"]}`

        异常统一转 `LlmApiError`，消息经 sk-* redact。
        """
        import httpx

        url = self.base_url.rstrip("/") + "/models"
        try:
            r = httpx.get(
                url,
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=self.timeout,
            )
            r.raise_for_status()
            data = r.json()
        except BaseException as e:  # noqa: BLE001
            msg = redact_sk(f"{type(e).__name__}: {e}")
            raise LlmApiError(
                f"LLM list_models failed: {msg}",
                details={"base_url": self.base_url},
            ) from None

        ids = _extract_model_ids(data)
        return sorted(set(ids))

    def chat(
        self,
        messages: list[dict],
        *,
        model: str | None = None,
        **kwargs: Any,
    ) -> str:
        """调用 `chat.completions.create`，返回 `choices[0].message.content`。

        - model 默认用 provider 配置里的 `model`，可显式覆盖
        - kwargs 透传给 openai SDK（temperature / max_tokens / response_format 等）
        - 异常统一转 `LlmApiError`，消息经 sk-* redact
        """
        cli = self._ensure_client()
        use_model = model or self.default_model
        try:
            resp = cli.chat.completions.create(
                model=use_model, messages=messages, **kwargs,
            )
        except BaseException as e:  # noqa: BLE001
            msg = redact_sk(f"{type(e).__name__}: {e}")
            raise LlmApiError(
                f"LLM call failed: {msg}",
                details={"model": use_model, "base_url": self.base_url},
            ) from None  # 丢弃 cause，避免原 exception repr 再次泄露
        # 响应结构：choices[0].message.content
        try:
            return resp.choices[0].message.content or ""
        except (AttributeError, IndexError) as e:
            raise LlmApiError(
                f"Unexpected LLM response shape: {e}",
                details={"model": use_model},
            ) from e
