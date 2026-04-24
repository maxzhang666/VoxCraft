"""Provider 能力声明的中央常量表。

每个 Provider 类通过 `CAPABILITIES: frozenset[str]` 声明其能力（ADR-014）。
编排层（如 /video-translate）据此做前置验证，避免"传了不支持克隆的 Provider 却要求克隆"等错误在运行时才暴露。

新增能力时在此处加常量；避免在 Provider 侧直接写裸字符串。
"""
from __future__ import annotations

# 声纹克隆：接受参考音频，合成同音色但内容不同的语音。
# 典型 Provider：VoxCPM / IndexTTS。Piper / faster-whisper 不具备。
CLONE = "clone"

# 预留：未来扩展
# STREAMING = "streaming"       # 流式推理
# DIARIZATION = "diarization"   # 说话人分离
