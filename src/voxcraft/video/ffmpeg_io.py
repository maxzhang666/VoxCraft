"""FFmpeg 胶水：probe / demux / mux（ADR-014）。

所有函数为同步阻塞调用，走 ffmpeg-python（subprocess 包装）。由调度层
（runtime.scheduler）在后台 runner 中执行，不在请求协程里直接跑。

依赖：
- Python：`ffmpeg-python>=0.2.0`（本模块）
- 系统：`ffmpeg` 二进制（Dockerfile 运行时层预装）
- 字体：`fonts-noto-cjk`（仅硬字幕烧录中文需要）
"""
from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from voxcraft.errors import MediaDecodeError


SubtitleMode = Literal["soft", "hard", "none"]


@dataclass(frozen=True)
class MediaInfo:
    """ffprobe 提取的关键字段。"""
    path: str
    is_video: bool             # True = 含视频流；False = 纯音频
    duration: float            # 秒
    video_codec: str | None
    audio_codec: str | None
    width: int | None
    height: int | None


def _require_ffmpeg() -> None:
    """启动期自检。找不到 ffmpeg 二进制即刻抛错，避免延迟到运行中段暴露。"""
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        raise MediaDecodeError(
            "ffmpeg/ffprobe not found in PATH; "
            "install system ffmpeg (Dockerfile runtime layer preinstalls it)",
            code="MEDIA_DECODE_ERROR",
        )


def probe(path: str | Path) -> MediaInfo:
    """读取媒体文件元信息。失败抛 MediaDecodeError。"""
    _require_ffmpeg()
    p = Path(path)
    if not p.exists() or not p.is_file():
        raise MediaDecodeError(f"media not found: {p}", details={"path": str(p)})

    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_format", "-show_streams",
                "-of", "json", str(p),
            ],
            capture_output=True, text=True, check=True, timeout=30,
        )
        data = json.loads(result.stdout)
    except subprocess.CalledProcessError as e:
        raise MediaDecodeError(
            f"ffprobe failed: {e.stderr.strip() or 'unknown error'}",
            details={"path": str(p)},
        ) from e
    except (subprocess.TimeoutExpired, json.JSONDecodeError) as e:
        raise MediaDecodeError(
            f"ffprobe probe unusable: {e}", details={"path": str(p)},
        ) from e

    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)

    if audio is None:
        raise MediaDecodeError(
            "no audio stream found; video translation requires audio",
            details={"path": str(p)},
        )

    try:
        duration = float(data.get("format", {}).get("duration", 0.0))
    except (TypeError, ValueError):
        duration = 0.0

    return MediaInfo(
        path=str(p),
        is_video=video is not None,
        duration=duration,
        video_codec=video.get("codec_name") if video else None,
        audio_codec=audio.get("codec_name"),
        width=int(video["width"]) if video and "width" in video else None,
        height=int(video["height"]) if video and "height" in video else None,
    )


def extract_audio(
    source_path: str | Path,
    out_wav_path: str | Path,
    *,
    sample_rate: int = 16000,
    mono: bool = True,
    start_seconds: float | None = None,
    duration_seconds: float | None = None,
) -> None:
    """把输入媒体的音轨解码为 PCM WAV（默认 16kHz mono，ASR 友好）。

    可选 start_seconds/duration_seconds 把输出裁剪为 [start, start+duration) 区间——
    抽取声纹时用得上（避免上传整段长视频后又得人工裁剪到 3-10s）。
    `-ss` 放在 `-i` 之后走精确 seek（解码到精确帧），短片段裁剪精度优先于速度。
    覆盖同名文件；父目录需已存在。
    """
    _require_ffmpeg()
    src = Path(source_path)
    dst = Path(out_wav_path)
    if not src.exists():
        raise MediaDecodeError(f"source not found: {src}")
    if start_seconds is not None and start_seconds < 0:
        raise MediaDecodeError(f"start_seconds must be >= 0, got {start_seconds}")
    if duration_seconds is not None and duration_seconds <= 0:
        raise MediaDecodeError(f"duration_seconds must be > 0, got {duration_seconds}")

    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(src)]
    if start_seconds is not None:
        cmd += ["-ss", f"{start_seconds:.3f}"]
    if duration_seconds is not None:
        cmd += ["-t", f"{duration_seconds:.3f}"]
    cmd += [
        "-vn",                              # 丢弃视频流
        "-ar", str(sample_rate),
        "-ac", "1" if mono else "2",
        "-f", "wav",
        str(dst),
    ]
    _run_ffmpeg(cmd, context={
        "op": "extract_audio",
        "src": str(src),
        "start_seconds": start_seconds,
        "duration_seconds": duration_seconds,
    })


def mux_video(
    video_path: str | Path,
    new_audio_path: str | Path,
    out_path: str | Path,
    *,
    srt_path: str | Path | None = None,
    subtitle_mode: SubtitleMode = "soft",
) -> None:
    """音轨替换 + 按 subtitle_mode 处理字幕。

    - soft：字幕作 mov_text 轨道装进容器；无需重编码视频
    - hard：用 subtitles filter 烧录到画面；需重编码视频（慢）
    - none：只替换音轨，丢弃字幕

    不改动原视频的分辨率、帧率、码率（定位：胶水，不做转码）。
    video_path 仅作视频流来源；new_audio_path 作音频流来源。
    """
    _require_ffmpeg()
    vp = Path(video_path)
    ap = Path(new_audio_path)
    op = Path(out_path)
    if not vp.exists():
        raise MediaDecodeError(f"video not found: {vp}")
    if not ap.exists():
        raise MediaDecodeError(f"audio not found: {ap}")

    if subtitle_mode not in ("soft", "hard", "none"):
        raise MediaDecodeError(f"invalid subtitle_mode: {subtitle_mode}")

    if subtitle_mode != "none" and srt_path is None:
        raise MediaDecodeError(
            f"subtitle_mode={subtitle_mode} requires srt_path", details={
                "subtitle_mode": subtitle_mode
            },
        )

    cmd: list[str] = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(vp),
        "-i", str(ap),
    ]

    if subtitle_mode == "hard":
        # 硬烧录：subtitles filter 读取 srt；视频重编码
        srt = Path(srt_path) if srt_path else None
        assert srt is not None
        # filter 参数里的冒号/反斜杠在 ffmpeg 语法里有特殊含义，做最小转义
        srt_arg = str(srt).replace("\\", "\\\\").replace(":", "\\:")
        cmd += [
            "-map", "0:v:0", "-map", "1:a:0",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-vf", f"subtitles={srt_arg}",
            "-c:a", "aac", "-b:a", "192k",
        ]
    elif subtitle_mode == "soft":
        srt = Path(srt_path) if srt_path else None
        assert srt is not None
        cmd += [
            "-i", str(srt),
            "-map", "0:v:0", "-map", "1:a:0", "-map", "2:s:0",
            "-c:v", "copy",
            "-c:a", "aac", "-b:a", "192k",
            "-c:s", "mov_text",
        ]
    else:  # none
        cmd += [
            "-map", "0:v:0", "-map", "1:a:0",
            "-c:v", "copy",
            "-c:a", "aac", "-b:a", "192k",
        ]

    cmd.append(str(op))
    _run_ffmpeg(cmd, context={
        "op": "mux_video",
        "subtitle_mode": subtitle_mode,
    })


def concat_audio(
    segment_paths: list[str | Path],
    out_wav_path: str | Path,
    *,
    sample_rate: int = 16000,
) -> None:
    """把多段 WAV 按顺序拼接成一段（无间隔）。

    用 `concat` filter，强制重采样到 `sample_rate`（避免各段 SR 不一致导致拼接失败）。
    """
    _require_ffmpeg()
    if not segment_paths:
        raise MediaDecodeError("concat_audio called with empty segment list")

    cmd: list[str] = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
    ]
    for p in segment_paths:
        path = Path(p)
        if not path.exists():
            raise MediaDecodeError(f"segment not found: {path}")
        cmd += ["-i", str(path)]

    n = len(segment_paths)
    filter_inputs = "".join(f"[{i}:a:0]" for i in range(n))
    filter_complex = (
        f"{filter_inputs}concat=n={n}:v=0:a=1[outa]"
    )
    cmd += [
        "-filter_complex", filter_complex,
        "-map", "[outa]",
        "-ar", str(sample_rate),
        "-ac", "1",
        str(out_wav_path),
    ]
    _run_ffmpeg(cmd, context={"op": "concat_audio", "n_segments": n})


def _run_ffmpeg(cmd: list[str], *, context: dict) -> None:
    try:
        subprocess.run(cmd, capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as e:
        raise MediaDecodeError(
            f"ffmpeg failed: {e.stderr.strip()[:500] or 'unknown error'}",
            details={**context, "stderr_tail": e.stderr.strip()[-500:]},
        ) from e
    except FileNotFoundError as e:
        raise MediaDecodeError(
            f"ffmpeg binary missing: {e}", details=context,
        ) from e
