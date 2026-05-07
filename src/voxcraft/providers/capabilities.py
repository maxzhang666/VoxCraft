"""Provider 能力声明的中央常量表。

每个 Provider 类通过 `CAPABILITIES: frozenset[str]` 声明其能力（ADR-014）。
编排层据此做前置验证，避免在运行时才暴露能力错配。

新增能力时在此处加常量；避免在 Provider 侧直接写裸字符串。
"""
from __future__ import annotations

# 当前没有需要 capability 区分的 Provider 行为；常量留作未来扩展。
# 历史：CLONE = "clone" 在 voice cloning 整体下线时移除。

# 预留：未来扩展
# STREAMING = "streaming"       # 流式推理
# DIARIZATION = "diarization"   # 说话人分离
