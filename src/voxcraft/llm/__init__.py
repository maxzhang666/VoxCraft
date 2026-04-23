"""LLM 接入公共基建（v0.3.0 / plans/voxcraft-llm-integration）。

对外暴露 `LlmClient`；消费者（翻译 / 摘要 / 字幕润色等）通过
`LlmClient.from_db(session, name=None)` 获取客户端并调 `chat()`。
"""
from voxcraft.llm.client import LlmClient

__all__ = ["LlmClient"]
