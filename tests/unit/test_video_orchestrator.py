"""视频翻译编排器单元测试（ADR-014 / 阶段 3）。

用本地 mock Provider + 注入 llm_chat_fn，验证 5 阶段编排、产物、
进度回调、LLM 软降级。真 ffmpeg 依赖沿用 tests/unit/test_ffmpeg_io.py 的做法。
"""
from __future__ import annotations

import io
import shutil
import subprocess
import wave
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from voxcraft.errors import LlmApiError
from voxcraft.providers import registry
from voxcraft.providers.base import (
    AsrProvider,
    AsrResult,
    AsrSegment,
    ProviderInfo,
    TtsProvider,
    Voice,
)
from voxcraft.runtime.scheduler_api import JobRequest
from voxcraft.runtime.worker_runners import _LruOne
from voxcraft.video.orchestrator import run_video_translate


pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="system ffmpeg/ffprobe not available",
)


# ---------- 本地 mocks ----------

class _ProgrammableAsr(AsrProvider):
    """可编程 ASR：通过 config['segments'] 传入 [(start, end, text), ...]。"""

    def load(self) -> None:
        self._loaded = True

    def unload(self) -> None:
        self._loaded = False

    def info(self) -> ProviderInfo:
        return ProviderInfo(
            kind="asr", name=self.name, class_name=type(self).__name__,
            loaded=self._loaded,
        )

    def transcribe(self, audio_path, language=None, progress_cb=None):
        if progress_cb:
            progress_cb(0.5)
            progress_cb(1.0)
        segs = self.config.get("segments", [(0.0, 1.0, "hello")])
        return AsrResult(
            segments=[AsrSegment(start=s, end=e, text=t) for s, e, t in segs],
            language=language or "en",
            duration=max(e for _, e, _ in segs),
        )


class _WavTtsProvider(TtsProvider):
    """生成 tiny 真 WAV，每段 0.5 秒静音。"""

    def load(self) -> None:
        self._loaded = True

    def unload(self) -> None:
        self._loaded = False

    def info(self) -> ProviderInfo:
        return ProviderInfo(
            kind="tts", name=self.name, class_name=type(self).__name__,
            loaded=self._loaded,
        )

    def synthesize(self, text, voice_id, speed=1.0, format="wav") -> bytes:
        return _tiny_wav(duration=0.5)

    def list_voices(self) -> list[Voice]:
        return [Voice(id="mock", language="en")]


def _tiny_wav(duration: float = 0.5, sr: int = 16000) -> bytes:
    buf = io.BytesIO()
    w = wave.open(buf, "wb")
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(sr)
    w.writeframes(b"\x00\x00" * int(sr * duration))
    w.close()
    return buf.getvalue()


# ---------- fixtures ----------

@pytest.fixture(autouse=True)
def _register_mocks(monkeypatch):
    monkeypatch.setitem(
        registry.PROVIDER_REGISTRY, "_ProgrammableAsr", _ProgrammableAsr,
    )
    monkeypatch.setitem(
        registry.PROVIDER_REGISTRY, "_WavTtsProvider", _WavTtsProvider,
    )


@pytest.fixture
def tiny_audio_input(tmp_path: Path) -> Path:
    """2 秒 mono sine，作为 orchestrator 的 source_path。"""
    out = tmp_path / "input.wav"
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
def tiny_video_input(tmp_path: Path) -> Path:
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


def _make_req(
    source: Path, out_dir: Path, *,
    asr_segments: list[tuple[float, float, str]] | None = None,
    subtitle_mode: str = "soft",
) -> JobRequest:
    return JobRequest(
        job_id="orch-test-1",
        kind="video_translate",
        provider_name="video-translate",
        class_name="VideoTranslateOrchestrator",
        provider_config={},
        request_meta={
            "asr": {
                "class_name": "_ProgrammableAsr",
                "name": "mock-asr",
                "config": {"segments": asr_segments or [
                    (0.0, 1.0, "hello world"),
                    (1.0, 2.0, "goodbye friend"),
                ]},
            },
            "tts": {
                "class_name": "_WavTtsProvider",
                "name": "mock-tts",
                "config": {},
            },
            "llm": {"base_url": "x", "api_key": "sk-test", "model": "m"},
            "target_lang": "zh",
            "source_lang": "en",
            "subtitle_mode": subtitle_mode,
            "clone_voice": False,
            "align_mode": "natural",
            "align_max_speedup": 1.3,
            "system_prompt": None,
        },
        source_path=str(source),
        output_dir=str(out_dir),
    )


@dataclass
class _FakeLlm:
    responses: list[str]
    calls: list[str] = field(default_factory=list)

    def __call__(self, messages: list[dict], *, model: str | None = None) -> str:
        user_text = messages[-1]["content"]
        self.calls.append(user_text)
        return self.responses.pop(0) if self.responses else user_text


# ---------- 正常路径 ----------

def test_result_contains_segments_detail(tiny_audio_input: Path, tmp_path: Path):
    """result.segments 每段带对照信息，供前端详情页渲染。"""
    req = _make_req(tiny_audio_input, tmp_path)
    llm = _FakeLlm(responses=["你好世界", "再见朋友"])
    result = run_video_translate(req, _LruOne(), emit=None, llm_chat_fn=llm)

    assert result.ok
    segs = result.result["segments"]
    assert len(segs) == 2
    keys = {"index", "orig_start", "orig_end", "final_start", "final_end",
            "speed", "drift", "source_text", "translated_text", "untranslated"}
    assert set(segs[0].keys()) == keys
    assert segs[0]["source_text"] == "hello world"
    assert segs[0]["translated_text"] == "你好世界"
    assert segs[0]["untranslated"] is False


def test_result_segments_mark_untranslated(tiny_audio_input: Path, tmp_path: Path):
    """空 LLM 输出触发回退，segment.untranslated=True 前端能标红。"""
    req = _make_req(tiny_audio_input, tmp_path)
    llm = _FakeLlm(responses=["", "正常译文"])
    result = run_video_translate(req, _LruOne(), emit=None, llm_chat_fn=llm)

    segs = result.result["segments"]
    assert segs[0]["untranslated"] is True
    assert segs[0]["translated_text"].startswith("[untranslated]")
    assert segs[1]["untranslated"] is False


def test_audio_input_produces_subtitle_and_audio(
    tiny_audio_input: Path, tmp_path: Path,
):
    req = _make_req(tiny_audio_input, tmp_path)
    llm = _FakeLlm(responses=["你好世界", "再见朋友"])
    lru = _LruOne()

    result = run_video_translate(req, lru, emit=None, llm_chat_fn=llm)

    assert result.ok, result.error_message
    assert result.output_extras is not None
    assert "subtitle" in result.output_extras
    assert "audio" in result.output_extras
    assert "video" not in result.output_extras  # 音频输入无视频产物
    # 主产物应指向 audio（音频输入）
    assert result.output_path == result.output_extras["audio"]

    subtitle = Path(result.output_extras["subtitle"])
    srt = subtitle.read_text(encoding="utf-8")
    assert "你好世界" in srt and "再见朋友" in srt

    audio = Path(result.output_extras["audio"])
    assert audio.exists() and audio.stat().st_size > 0

    # LLM 每段被调一次
    assert len(llm.calls) == 2


def test_video_input_produces_all_three(tiny_video_input: Path, tmp_path: Path):
    req = _make_req(tiny_video_input, tmp_path, subtitle_mode="none")
    llm = _FakeLlm(responses=["A", "B"])
    lru = _LruOne()

    result = run_video_translate(req, lru, emit=None, llm_chat_fn=llm)

    assert result.ok, result.error_message
    extras = result.output_extras
    assert extras is not None
    for key in ("subtitle", "audio", "video"):
        assert key in extras and Path(extras[key]).exists()
    assert result.output_path == extras["video"]  # 视频输入主产物 = video


def test_progress_callback_covers_all_stages(
    tiny_audio_input: Path, tmp_path: Path,
):
    events: list[dict] = []
    req = _make_req(tiny_audio_input, tmp_path)
    llm = _FakeLlm(responses=["x", "y"])
    lru = _LruOne()

    run_video_translate(req, lru, emit=events.append, llm_chat_fn=llm)

    progs = [e["progress"] for e in events if e.get("type") == "job_progress"]
    assert progs, "at least one job_progress event expected"
    assert progs[-1] == pytest.approx(1.0, abs=0.05)
    # 至少见过 >0.5 的中间进度
    assert max(progs) > 0.5


def test_scratch_dir_cleaned_after_run(tiny_audio_input: Path, tmp_path: Path):
    req = _make_req(tiny_audio_input, tmp_path)
    llm = _FakeLlm(responses=["a", "b"])
    run_video_translate(req, _LruOne(), emit=None, llm_chat_fn=llm)

    scratch = tmp_path / "scratch" / req.job_id
    assert not scratch.exists()


# ---------- LLM 软降级 ----------

def test_llm_empty_output_fallback_to_source(
    tiny_audio_input: Path, tmp_path: Path,
):
    req = _make_req(tiny_audio_input, tmp_path)
    llm = _FakeLlm(responses=["", "正常译文"])
    result = run_video_translate(req, _LruOne(), emit=None, llm_chat_fn=llm)

    assert result.ok
    warnings = result.result["warnings"]
    assert any("empty output" in w for w in warnings)

    srt = Path(result.output_extras["subtitle"]).read_text(encoding="utf-8")
    assert "[untranslated]" in srt
    assert "正常译文" in srt


def test_llm_markdown_output_fallback(tiny_audio_input: Path, tmp_path: Path):
    req = _make_req(tiny_audio_input, tmp_path)
    llm = _FakeLlm(responses=["```\nCode fence inside\n```", "ok"])
    result = run_video_translate(req, _LruOne(), emit=None, llm_chat_fn=llm)

    assert result.ok
    assert any("markdown" in w for w in result.result["warnings"])


def test_llm_extreme_inflation_fallback(tiny_audio_input: Path, tmp_path: Path):
    req = _make_req(tiny_audio_input, tmp_path)
    long = "x" * 500
    llm = _FakeLlm(responses=[long, "ok"])
    result = run_video_translate(req, _LruOne(), emit=None, llm_chat_fn=llm)

    assert result.ok
    assert any("inflation" in w for w in result.result["warnings"])


def test_llm_metadata_leak_fallback(tiny_audio_input: Path, tmp_path: Path):
    req = _make_req(tiny_audio_input, tmp_path)
    llm = _FakeLlm(responses=["<thinking>translating</thinking>", "ok"])
    result = run_video_translate(req, _LruOne(), emit=None, llm_chat_fn=llm)

    assert result.ok
    assert any("metadata leak" in w for w in result.result["warnings"])


def test_llm_api_error_fails_job(tiny_audio_input: Path, tmp_path: Path):
    req = _make_req(tiny_audio_input, tmp_path)

    def failing_llm(messages, *, model=None):
        raise LlmApiError("upstream 503", code="LLM_API_ERROR")

    result = run_video_translate(
        req, _LruOne(), emit=None, llm_chat_fn=failing_llm,
    )
    assert result.ok is False
    assert result.error_code == "LLM_API_ERROR"


# ---------- LRU 切换行为 ----------

def test_lru_switches_asr_to_tts(tiny_audio_input: Path, tmp_path: Path):
    req = _make_req(tiny_audio_input, tmp_path)
    llm = _FakeLlm(responses=["a", "b"])
    lru = _LruOne()

    result = run_video_translate(req, lru, emit=None, llm_chat_fn=llm)

    assert result.ok
    # 最终驻留应是 TTS
    assert isinstance(lru.current, _WavTtsProvider)
    assert lru.current.loaded
