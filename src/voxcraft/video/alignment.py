"""时间轴对齐策略（ADR-014 §4 / v0.4.0 阶段 4）。

设计：两阶段对齐，不做二次 TTS 合成。

  source segments (ASR, 带 start/end, text=译文)
      │
      │  plan_alignment(mode, max_speedup)
      ▼
  planned segments (speed_i, text_i)
      │  用 speed_i 一次合成 TTS
      ▼
  seg_audio_paths[] + measured_durations[]
      │
      │  finalize_alignment(planned, measured_durations)
      ▼
  aligned segments (final_start, final_end, drift)
      │  ← SRT 时间戳以此为准
      ▼
  concat_audio（无缝拼接）


三种模式差异只在 **speed**：
- natural：speed=1.0；译文自然时长
- elastic：speed 按 estimated_duration / slot 裁到 [1.0, max_speedup]，slot = next.start - cur.start
- strict：speed = estimated_duration / orig_duration，裁到 [1.0, 2.0]

字符数 × estimated_speech_rate 估算时长（粗糙；真实误差由 finalize 阶段基于测量值吸收）。

SRT 时间戳 = 累计测量时长 → 音频与字幕自洽；视频音轨替换后画面对不齐原对白是可接受代价
（ADR-014 §4 声明：追求 AV 同步的应用应选 strict 模式）。
"""
from __future__ import annotations

import logging
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

AlignMode = Literal["natural", "elastic", "strict"]

log = logging.getLogger(__name__)


# 字符/秒粗估（中文 ~4 字/s，英文 ~3 词/s，取中值）
DEFAULT_SPEECH_RATE = 3.5
MIN_SEGMENT_DURATION = 0.3

# strict 模式的内部 speed 上限（容忍较大失真但不失真到语义失联）
STRICT_SPEED_CAP = 2.0
# 绝对下限：永远不降速（speed<1 让 TTS 变慢，无益于对齐）
MIN_SPEED = 1.0


@dataclass(frozen=True)
class SourceSegment:
    """ASR 输出的原始 segment 视图（text 已替换为译文）。"""
    index: int
    start: float
    end: float
    text: str

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


@dataclass(frozen=True)
class PlannedSegment:
    """plan 阶段的产物：驱动 TTS 合成。"""
    index: int
    text: str
    speed: float
    orig_start: float
    orig_end: float
    estimated_duration: float  # 基于字符数 × 语速


@dataclass(frozen=True)
class AlignedSegment:
    """finalize 阶段的产物：驱动 SRT 时间戳。"""
    index: int
    final_start: float
    final_end: float
    speed: float
    text: str
    drift: float  # final_start - orig_start；>0 = 后移


# ---------- 外部 API ----------

def plan_alignment(
    segments: list[SourceSegment],
    *,
    mode: AlignMode = "natural",
    max_speedup: float = 1.3,
    rate: float = DEFAULT_SPEECH_RATE,
) -> list[PlannedSegment]:
    """根据模式为每段决定 TTS 合成速率。"""
    if not segments:
        return []
    if mode == "natural":
        return _plan_natural(segments, rate)
    if mode == "elastic":
        return _plan_elastic(segments, rate, max_speedup)
    if mode == "strict":
        return _plan_strict(segments, rate)
    log.warning("alignment.unknown_mode mode=%s fallback=natural", mode)
    return _plan_natural(segments, rate)


def finalize_alignment(
    planned: list[PlannedSegment],
    measured_durations: list[float],
) -> list[AlignedSegment]:
    """用 TTS 合成后的真实时长拼出 SRT 时间戳。

    SRT 时间轴锚定到合成音频的累计位置（音字自洽）；`drift` 相对原时间戳。
    """
    if len(planned) != len(measured_durations):
        raise ValueError(
            f"planned/measured length mismatch: {len(planned)} vs {len(measured_durations)}",
        )
    out: list[AlignedSegment] = []
    cursor = 0.0
    for p, actual in zip(planned, measured_durations, strict=True):
        actual = max(MIN_SEGMENT_DURATION, actual)
        final_start = cursor
        final_end = cursor + actual
        out.append(
            AlignedSegment(
                index=p.index,
                final_start=final_start,
                final_end=final_end,
                speed=p.speed,
                text=p.text,
                drift=final_start - p.orig_start,
            )
        )
        cursor = final_end
    return out


def wav_duration(path: str | Path) -> float:
    """读取 WAV 头拿时长，秒。非 WAV 或损坏文件抛 ValueError。"""
    with wave.open(str(path), "rb") as w:
        frames = w.getnframes()
        rate = w.getframerate()
    if rate <= 0:
        raise ValueError(f"invalid sample rate in {path}")
    return frames / rate


# ---------- 单模式 plan 实现 ----------

def _estimate(text: str, rate: float) -> float:
    n = max(1, len(text.strip()))
    return max(MIN_SEGMENT_DURATION, n / max(0.5, rate))


def _plan_natural(
    segments: list[SourceSegment], rate: float,
) -> list[PlannedSegment]:
    return [
        PlannedSegment(
            index=s.index, text=s.text, speed=1.0,
            orig_start=s.start, orig_end=s.end,
            estimated_duration=_estimate(s.text, rate),
        )
        for s in segments
    ]


def _plan_elastic(
    segments: list[SourceSegment], rate: float, max_speedup: float,
) -> list[PlannedSegment]:
    """按原起始点 → 下一段起始点定义 slot，估算时长溢出时压缩到 max_speedup。

    speed = clamp(estimated / slot, 1.0, max_speedup)
    """
    out: list[PlannedSegment] = []
    n = len(segments)
    max_speedup = max(MIN_SPEED, max_speedup)
    for i, s in enumerate(segments):
        if i + 1 < n:
            slot = max(MIN_SEGMENT_DURATION, segments[i + 1].start - s.start)
        else:
            # 最后一段：用原段时长作为 slot
            slot = max(MIN_SEGMENT_DURATION, s.duration)
        est = _estimate(s.text, rate)
        if est <= slot:
            speed = 1.0
        else:
            speed = min(max_speedup, est / slot)
        out.append(
            PlannedSegment(
                index=s.index, text=s.text, speed=speed,
                orig_start=s.start, orig_end=s.end,
                estimated_duration=est,
            )
        )
    return out


def _plan_strict(
    segments: list[SourceSegment], rate: float,
) -> list[PlannedSegment]:
    """强制压缩到原段时长。speed = clamp(estimated/orig_duration, 1.0, 2.0)。"""
    out: list[PlannedSegment] = []
    for s in segments:
        orig_dur = max(MIN_SEGMENT_DURATION, s.duration)
        est = _estimate(s.text, rate)
        if est <= orig_dur:
            speed = 1.0
        else:
            speed = min(STRICT_SPEED_CAP, est / orig_dur)
        out.append(
            PlannedSegment(
                index=s.index, text=s.text, speed=speed,
                orig_start=s.start, orig_end=s.end,
                estimated_duration=est,
            )
        )
    return out


# ---------- 向后兼容：单步 API（阶段 3 使用）----------

def align(
    segments: list[SourceSegment],
    *,
    mode: AlignMode = "natural",
    max_speedup: float = 1.3,
    rate: float = DEFAULT_SPEECH_RATE,
) -> list[AlignedSegment]:
    """单步对齐：用 plan 阶段估算时长作为 finalize 的输入。

    仅在无测量数据时使用（如只做 SRT、不关心音频对齐）。orchestrator 正常路径
    应用 `plan_alignment` + `finalize_alignment` 两步法。
    """
    planned = plan_alignment(
        segments, mode=mode, max_speedup=max_speedup, rate=rate,
    )
    estimated_actual = [
        max(MIN_SEGMENT_DURATION, p.estimated_duration / max(MIN_SPEED, p.speed))
        for p in planned
    ]
    return finalize_alignment(planned, estimated_actual)
