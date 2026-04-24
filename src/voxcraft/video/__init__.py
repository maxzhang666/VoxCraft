"""视频处理胶水层（ADR-014）。

提供 ffmpeg 基础能力（probe / demux / mux + 字幕嵌入），供 /video-translate
编排器使用。定位仅为"AI 链路的输入输出胶水"，不做剪辑/转码/滤镜/特效。
"""
from __future__ import annotations

from voxcraft.video.ffmpeg_io import (
    MediaInfo,
    concat_audio,
    extract_audio,
    mux_video,
    probe,
)

__all__ = ["MediaInfo", "concat_audio", "extract_audio", "mux_video", "probe"]
