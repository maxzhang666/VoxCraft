"""SRT 字幕生成（ADR-014 / v0.4.0）。

仅处理格式化；时间戳对齐由 alignment.py 决定。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SrtSegment:
    index: int          # 1-based
    start: float        # 秒
    end: float
    text: str


def _fmt_ts(t: float) -> str:
    """SRT 时间戳：HH:MM:SS,mmm。"""
    if t < 0:
        t = 0.0
    total_ms = int(round(t * 1000))
    h, rem = divmod(total_ms, 3600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def segments_to_srt(segments: list[SrtSegment]) -> str:
    lines: list[str] = []
    for seg in segments:
        lines.append(str(seg.index))
        lines.append(f"{_fmt_ts(seg.start)} --> {_fmt_ts(seg.end)}")
        lines.append(seg.text.strip() or "[untranslated]")
        lines.append("")  # 段落间空行
    return "\n".join(lines) + "\n"
