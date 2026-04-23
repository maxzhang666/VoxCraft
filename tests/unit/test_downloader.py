"""Downloader 分支契约（mock snapshot_download / httpx / torch）。"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from voxcraft.errors import DownloadError
from voxcraft.models_lib import downloader


# ---------- download_hf ----------

def test_download_hf_calls_snapshot_download(tmp_path):
    fake = MagicMock(return_value=str(tmp_path / "model"))
    with patch.object(downloader, "hf_snapshot_download", fake):
        result = downloader.download_hf("org/repo", tmp_path / "model", max_workers=8)
    fake.assert_called_once()
    kwargs = fake.call_args.kwargs
    assert kwargs["repo_id"] == "org/repo"
    assert kwargs["local_dir"] == str(tmp_path / "model")
    assert kwargs["max_workers"] == 8
    assert result == tmp_path / "model"


def test_download_hf_wraps_exception(tmp_path):
    def _raise(**_):
        raise RuntimeError("network")
    with patch.object(downloader, "hf_snapshot_download", _raise):
        with pytest.raises(DownloadError) as exc:
            downloader.download_hf("x/y", tmp_path / "m")
    assert exc.value.code == "DOWNLOAD_FAILED"


# ---------- download_ms ----------

def test_download_ms_calls_modelscope(tmp_path):
    fake = MagicMock(return_value=str(tmp_path / "m"))
    with patch.object(downloader, "ms_snapshot_download", fake):
        result = downloader.download_ms("org/repo", tmp_path / "m", max_workers=4)
    kwargs = fake.call_args.kwargs
    assert kwargs["model_id"] == "org/repo"
    assert kwargs["local_dir"] == str(tmp_path / "m")
    assert kwargs["max_workers"] == 4
    assert result == tmp_path / "m"


def test_download_ms_wraps_exception(tmp_path):
    def _raise(**_):
        raise ValueError("bad repo")
    with patch.object(downloader, "ms_snapshot_download", _raise):
        with pytest.raises(DownloadError):
            downloader.download_ms("x/y", tmp_path / "m")


# ---------- download_url ----------

def test_download_url_streams_to_file(tmp_path):
    import httpx

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"RIFFmodelbytes")

    transport = httpx.MockTransport(handler)
    target = tmp_path / "piper.onnx"

    with patch.object(
        downloader, "_build_httpx_client", lambda: httpx.Client(transport=transport)
    ):
        result = downloader.download_url("https://example.com/piper.onnx", target)

    assert result == target
    assert target.read_bytes() == b"RIFFmodelbytes"


def test_download_url_wraps_http_error(tmp_path):
    import httpx

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, content=b"not found")

    transport = httpx.MockTransport(handler)
    with patch.object(
        downloader, "_build_httpx_client", lambda: httpx.Client(transport=transport)
    ):
        with pytest.raises(DownloadError) as exc:
            downloader.download_url("https://example.com/x", tmp_path / "x")
    assert exc.value.code == "DOWNLOAD_FAILED"


# ---------- download_torch_hub ----------

def test_download_torch_hub_without_demucs_raises(tmp_path):
    """未装 demucs 时，分支应抛 DownloadError 给友好提示。"""
    # 实际环境未装 demucs，直接调用即可复现
    with pytest.raises(DownloadError) as exc:
        downloader.download_torch_hub("htdemucs", tmp_path / "demucs")
    assert "demucs" in exc.value.message.lower() or "torch" in exc.value.message.lower()
