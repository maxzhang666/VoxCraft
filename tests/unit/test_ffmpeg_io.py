"""FFmpeg 胶水层单元测试（ADR-014 阶段 1）。

需要系统 ffmpeg 二进制。测试用 ffmpeg 自身生成 tiny fixture，不依赖外部素材。
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from voxcraft.errors import MediaDecodeError
from voxcraft.video import extract_audio, mux_video, probe


pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="system ffmpeg/ffprobe not available",
)


# ---------- fixtures ----------

@pytest.fixture
def tiny_audio(tmp_path: Path) -> Path:
    """2 秒 440Hz 正弦波 WAV（mono, 16kHz）。"""
    out = tmp_path / "tone.wav"
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
            "-ar", "16000", "-ac", "1", str(out),
        ],
        check=True,
    )
    return out


@pytest.fixture
def tiny_video(tmp_path: Path) -> Path:
    """2 秒 160x120 测试卡视频 + 440Hz 音轨。"""
    out = tmp_path / "clip.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "testsrc=size=160x120:rate=15:duration=2",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(out),
        ],
        check=True,
    )
    return out


@pytest.fixture
def tiny_srt(tmp_path: Path) -> Path:
    out = tmp_path / "sub.srt"
    out.write_text(
        "1\n00:00:00,000 --> 00:00:02,000\nhello world\n",
        encoding="utf-8",
    )
    return out


# ---------- probe ----------

def test_probe_audio(tiny_audio: Path):
    info = probe(tiny_audio)
    assert info.is_video is False
    assert info.video_codec is None
    assert info.audio_codec is not None
    assert abs(info.duration - 2.0) < 0.3
    assert info.width is None and info.height is None


def test_probe_video(tiny_video: Path):
    info = probe(tiny_video)
    assert info.is_video is True
    assert info.video_codec == "h264"
    assert info.audio_codec is not None
    assert info.width == 160 and info.height == 120
    assert abs(info.duration - 2.0) < 0.3


def test_probe_missing_file(tmp_path: Path):
    with pytest.raises(MediaDecodeError):
        probe(tmp_path / "does_not_exist.mp4")


def test_probe_no_audio_stream(tmp_path: Path):
    # 生成纯视频（无音轨）
    silent = tmp_path / "silent.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "testsrc=size=160x120:rate=15:duration=1",
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
            str(silent),
        ],
        check=True,
    )
    with pytest.raises(MediaDecodeError, match="no audio stream"):
        probe(silent)


# ---------- extract_audio ----------

def test_extract_audio_from_video(tiny_video: Path, tmp_path: Path):
    out_wav = tmp_path / "extracted.wav"
    extract_audio(tiny_video, out_wav)
    assert out_wav.exists() and out_wav.stat().st_size > 0
    info = probe(out_wav)
    assert info.audio_codec == "pcm_s16le"
    assert abs(info.duration - 2.0) < 0.3


def test_extract_audio_from_audio(tiny_audio: Path, tmp_path: Path):
    """音频输入也支持，等价于格式/采样率规整。"""
    out_wav = tmp_path / "re.wav"
    extract_audio(tiny_audio, out_wav, sample_rate=16000, mono=True)
    assert out_wav.exists()
    info = probe(out_wav)
    assert info.audio_codec == "pcm_s16le"


def test_extract_audio_missing_source(tmp_path: Path):
    with pytest.raises(MediaDecodeError):
        extract_audio(tmp_path / "missing.mp4", tmp_path / "out.wav")


# ---------- mux_video ----------

def test_mux_none_replaces_audio(tiny_video: Path, tiny_audio: Path, tmp_path: Path):
    out = tmp_path / "out_none.mp4"
    mux_video(tiny_video, tiny_audio, out, subtitle_mode="none")
    assert out.exists()
    info = probe(out)
    assert info.is_video is True
    assert info.audio_codec is not None


def test_mux_soft_embeds_subtitle_track(
    tiny_video: Path, tiny_audio: Path, tiny_srt: Path, tmp_path: Path,
):
    out = tmp_path / "out_soft.mp4"
    mux_video(
        tiny_video, tiny_audio, out,
        srt_path=tiny_srt, subtitle_mode="soft",
    )
    assert out.exists()
    # 验证容器里有字幕流
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "s",
         "-show_entries", "stream=codec_name",
         "-of", "csv=p=0", str(out)],
        capture_output=True, text=True, check=True,
    )
    assert result.stdout.strip() != "", "no subtitle stream in soft-muxed output"


def test_mux_hard_burns_subtitles(
    tiny_video: Path, tiny_audio: Path, tiny_srt: Path, tmp_path: Path,
):
    out = tmp_path / "out_hard.mp4"
    mux_video(
        tiny_video, tiny_audio, out,
        srt_path=tiny_srt, subtitle_mode="hard",
    )
    assert out.exists()
    # 硬字幕不会有独立字幕流（已烧进画面）
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "s",
         "-show_entries", "stream=codec_name",
         "-of", "csv=p=0", str(out)],
        capture_output=True, text=True, check=True,
    )
    assert result.stdout.strip() == ""


def test_mux_soft_requires_srt(tiny_video: Path, tiny_audio: Path, tmp_path: Path):
    with pytest.raises(MediaDecodeError, match="requires srt_path"):
        mux_video(
            tiny_video, tiny_audio, tmp_path / "x.mp4",
            srt_path=None, subtitle_mode="soft",
        )


def test_mux_invalid_subtitle_mode(
    tiny_video: Path, tiny_audio: Path, tmp_path: Path,
):
    with pytest.raises(MediaDecodeError, match="invalid subtitle_mode"):
        mux_video(
            tiny_video, tiny_audio, tmp_path / "x.mp4",
            subtitle_mode="invalid",  # type: ignore[arg-type]
        )


def test_mux_missing_video(tmp_path: Path, tiny_audio: Path):
    with pytest.raises(MediaDecodeError):
        mux_video(
            tmp_path / "missing.mp4", tiny_audio,
            tmp_path / "out.mp4", subtitle_mode="none",
        )
