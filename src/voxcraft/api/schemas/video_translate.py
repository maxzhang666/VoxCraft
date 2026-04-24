"""视频翻译编排 schema（ADR-014 / v0.4.0）。

请求为 multipart/form-data；字段定义在路由层用 Form(...) 声明，这里维护
枚举与支持语言常量，供路由/测试统一引用。
"""
from __future__ import annotations

from enum import Enum


class SubtitleMode(str, Enum):
    """视频输出时字幕的嵌入方式（仅对视频输入生效）。"""
    soft = "soft"    # mov_text 字幕轨，播放器可开关；无需重编码
    hard = "hard"    # 用 subtitles filter 烧录到画面；需重编码
    none = "none"    # 不嵌字幕


class AlignMode(str, Enum):
    """翻译后 TTS 与原时间轴的对齐策略。"""
    elastic = "elastic"  # 按段起始点 + 溢出时语速压缩 + 仍溢出则后段顺延（默认）
    natural = "natural"  # 按译文自然时长拼接，忽略原时间戳
    strict = "strict"    # 强制匹配原 segment 时长（可能失真）


# 白名单：显式列举比 MIME 探测稳定可预期
VIDEO_EXTENSIONS = frozenset({".mp4", ".mkv", ".webm", ".mov", ".avi", ".flv", ".m4v"})
AUDIO_EXTENSIONS = frozenset({".wav", ".mp3", ".m4a", ".ogg", ".flac", ".aac"})
SUPPORTED_EXTENSIONS = VIDEO_EXTENSIONS | AUDIO_EXTENSIONS


# BCP-47 短码的常见子集。超出此列表仍可通过（LLM 宽容），只做格式校验。
# 规则：2-3 位小写字母主语码 + 可选 "-" 两位大写地区码（如 zh / zh-CN / en-US）。
import re

LANG_CODE_REGEX = re.compile(r"^[a-z]{2,3}(-[A-Z]{2})?$")


def is_valid_lang(code: str) -> bool:
    return bool(LANG_CODE_REGEX.match(code))


# 语速上下限
MIN_SPEEDUP = 1.0
MAX_SPEEDUP = 2.0

# system_prompt 长度上限（ADR-014）
MAX_SYSTEM_PROMPT_LEN = 2000
