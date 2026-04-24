"""时间轴对齐三模式（ADR-014 §4 / v0.4.0 阶段 4）。"""
from __future__ import annotations

import io
import wave
from pathlib import Path

import pytest

from voxcraft.video.alignment import (
    AlignedSegment,
    PlannedSegment,
    SourceSegment,
    align,
    finalize_alignment,
    plan_alignment,
    wav_duration,
)


def _segs(*rows: tuple[float, float, str]) -> list[SourceSegment]:
    return [
        SourceSegment(index=i + 1, start=s, end=e, text=t)
        for i, (s, e, t) in enumerate(rows)
    ]


# ---------- plan_alignment ----------

def test_plan_natural_always_speed_one():
    segs = _segs(
        (0.0, 1.0, "short"),
        (1.0, 2.0, "a" * 200),
    )
    planned = plan_alignment(segs, mode="natural")
    assert all(p.speed == 1.0 for p in planned)


def test_plan_elastic_speeds_up_when_text_overflows_slot():
    # 第一段 slot = 0.5s，text 很长 → 估算时长 >> slot → speed 提升
    segs = _segs(
        (0.0, 0.5, "这是一段非常长的中文译文应该会触发语速压缩" * 3),
        (0.5, 5.0, "短"),
    )
    planned = plan_alignment(segs, mode="elastic", max_speedup=1.3, rate=3.5)
    assert planned[0].speed > 1.0
    assert planned[0].speed <= 1.3 + 1e-9


def test_plan_elastic_stays_one_when_slot_is_ample():
    # text 短 + slot 宽裕
    segs = _segs(
        (0.0, 5.0, "hi"),
        (5.0, 10.0, "bye"),
    )
    planned = plan_alignment(segs, mode="elastic", max_speedup=1.3)
    assert planned[0].speed == 1.0
    assert planned[1].speed == 1.0


def test_plan_elastic_respects_max_speedup_cap():
    # 极端：text 远超 slot → 理论 speed 极大，应被 clamp 到 max_speedup
    segs = _segs(
        (0.0, 0.3, "x" * 1000),
        (0.3, 1.0, "y"),
    )
    planned = plan_alignment(segs, mode="elastic", max_speedup=1.2)
    assert planned[0].speed == pytest.approx(1.2, abs=1e-9)


def test_plan_strict_compresses_to_orig_duration():
    segs = _segs(
        (0.0, 0.5, "一段比原时长估计更长的译文内容"),
    )
    planned = plan_alignment(segs, mode="strict", rate=3.5)
    # estimated ≈ 15/3.5 ≈ 4.3s；orig_dur=0.5 → speed ≈ 8.6 被 clamp 到 STRICT_SPEED_CAP=2.0
    assert planned[0].speed == pytest.approx(2.0, abs=1e-9)


def test_plan_strict_stays_one_when_text_fits():
    segs = _segs((0.0, 10.0, "hi"))
    planned = plan_alignment(segs, mode="strict")
    assert planned[0].speed == 1.0


def test_plan_unknown_mode_falls_back_to_natural():
    segs = _segs((0.0, 1.0, "x"))
    planned = plan_alignment(segs, mode="invalid")  # type: ignore[arg-type]
    assert planned[0].speed == 1.0


def test_plan_empty_returns_empty():
    assert plan_alignment([]) == []


# ---------- finalize_alignment ----------

def test_finalize_cumulates_measured_durations():
    planned = [
        PlannedSegment(
            index=1, text="a", speed=1.0,
            orig_start=0.0, orig_end=0.5, estimated_duration=0.5,
        ),
        PlannedSegment(
            index=2, text="b", speed=1.2,
            orig_start=0.5, orig_end=2.0, estimated_duration=1.2,
        ),
    ]
    measured = [0.4, 1.0]
    aligned = finalize_alignment(planned, measured)

    assert [a.final_start for a in aligned] == [0.0, 0.4]
    assert [a.final_end for a in aligned] == [0.4, 1.4]
    # drift = final_start - orig_start
    assert aligned[0].drift == pytest.approx(0.0)
    assert aligned[1].drift == pytest.approx(-0.1)


def test_finalize_length_mismatch_raises():
    planned = [PlannedSegment(1, "a", 1.0, 0.0, 1.0, 0.5)]
    with pytest.raises(ValueError):
        finalize_alignment(planned, [0.5, 0.5])


def test_finalize_preserves_speed_and_text():
    planned = [
        PlannedSegment(
            index=7, text="hello", speed=1.3,
            orig_start=2.0, orig_end=3.0, estimated_duration=1.0,
        ),
    ]
    aligned = finalize_alignment(planned, [0.8])
    assert aligned[0].index == 7
    assert aligned[0].text == "hello"
    assert aligned[0].speed == 1.3


def test_finalize_enforces_min_duration():
    planned = [PlannedSegment(1, "x", 1.0, 0.0, 0.1, 0.1)]
    aligned = finalize_alignment(planned, [0.0])  # 测量返回 0 → 下限保底
    assert aligned[0].final_end - aligned[0].final_start >= 0.3


# ---------- wav_duration ----------

def _write_wav(path: Path, duration: float, sr: int = 16000) -> None:
    buf = io.BytesIO()
    w = wave.open(buf, "wb")
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(sr)
    w.writeframes(b"\x00\x00" * int(sr * duration))
    w.close()
    path.write_bytes(buf.getvalue())


def test_wav_duration_matches_frames(tmp_path: Path):
    p = tmp_path / "t.wav"
    _write_wav(p, duration=1.25)
    assert wav_duration(p) == pytest.approx(1.25, abs=0.001)


def test_wav_duration_invalid_file_raises(tmp_path: Path):
    bad = tmp_path / "bad.wav"
    bad.write_bytes(b"not a wav")
    with pytest.raises(Exception):
        wav_duration(bad)


# ---------- 向后兼容 align() ----------

def test_align_single_step_api_still_works():
    segs = _segs((0.0, 1.0, "hi"))
    aligned = align(segs, mode="natural")
    assert len(aligned) == 1
    assert isinstance(aligned[0], AlignedSegment)
    assert aligned[0].speed == 1.0
