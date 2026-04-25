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


# ---------- HF mirror rewrite ----------

def test_rewrite_hf_url_no_endpoint_returns_original(monkeypatch):
    monkeypatch.delenv("HF_ENDPOINT", raising=False)
    url = "https://huggingface.co/org/repo/resolve/main/model.onnx"
    assert downloader._rewrite_hf_url_for_mirror(url) == url


def test_rewrite_hf_url_replaces_host_when_endpoint_set(monkeypatch):
    monkeypatch.setenv("HF_ENDPOINT", "https://hf-mirror.com")
    url = "https://huggingface.co/org/repo/resolve/main/model.onnx"
    out = downloader._rewrite_hf_url_for_mirror(url)
    assert out == "https://hf-mirror.com/org/repo/resolve/main/model.onnx"


def test_rewrite_hf_url_preserves_query_and_fragment(monkeypatch):
    monkeypatch.setenv("HF_ENDPOINT", "https://hf-mirror.com")
    url = "https://huggingface.co/org/x/resolve/main/m.onnx?token=abc#frag"
    out = downloader._rewrite_hf_url_for_mirror(url)
    assert out == "https://hf-mirror.com/org/x/resolve/main/m.onnx?token=abc#frag"


def test_rewrite_hf_url_skips_non_huggingface_host(monkeypatch):
    monkeypatch.setenv("HF_ENDPOINT", "https://hf-mirror.com")
    url = "https://example.com/some/file.bin"
    assert downloader._rewrite_hf_url_for_mirror(url) == url


def test_rewrite_hf_url_skips_when_endpoint_invalid(monkeypatch):
    monkeypatch.setenv("HF_ENDPOINT", "")
    url = "https://huggingface.co/m.onnx"
    assert downloader._rewrite_hf_url_for_mirror(url) == url


def test_download_url_uses_hf_mirror(tmp_path, monkeypatch):
    """Piper-style direct URL should go through the configured HF mirror."""
    import httpx

    monkeypatch.setenv("HF_ENDPOINT", "https://hf-mirror.com")
    seen_urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_urls.append(str(request.url))
        return httpx.Response(200, content=b"RIFFok")

    transport = httpx.MockTransport(handler)
    target = tmp_path / "piper.onnx"
    with patch.object(
        downloader, "_build_httpx_client",
        lambda: httpx.Client(transport=transport),
    ):
        downloader.download_url(
            "https://huggingface.co/rhasspy/piper-voices/resolve/main/zh.onnx",
            target,
        )
    # 主文件 URL 已重写
    assert any(u.startswith("https://hf-mirror.com/") for u in seen_urls)
    assert not any(u.startswith("https://huggingface.co/") for u in seen_urls)


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


def test_download_url_fetches_piper_sidecar(tmp_path):
    """.onnx URL 应自动拉取同名 .onnx.json 配置（Piper 约定）。"""
    import httpx

    served: dict[str, bytes] = {
        "https://example.com/piper.onnx": b"ONNX_WEIGHTS",
        "https://example.com/piper.onnx.json": b'{"audio": {"sample_rate": 22050}}',
    }

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url in served:
            return httpx.Response(200, content=served[url])
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    target = tmp_path / "piper.onnx"

    with patch.object(
        downloader, "_build_httpx_client", lambda: httpx.Client(transport=transport)
    ):
        result = downloader.download_url("https://example.com/piper.onnx", target)

    assert result == target
    assert target.read_bytes() == b"ONNX_WEIGHTS"
    sidecar = tmp_path / "piper.onnx.json"
    assert sidecar.exists()
    assert b"sample_rate" in sidecar.read_bytes()


def test_download_url_tolerates_missing_sidecar(tmp_path):
    """sidecar 下载失败（如非 Piper 的 URL）不应拉起主调用。"""
    import httpx

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith(".json"):
            return httpx.Response(404)  # sidecar 不存在
        return httpx.Response(200, content=b"MAIN")

    transport = httpx.MockTransport(handler)
    target = tmp_path / "x.onnx"

    with patch.object(
        downloader, "_build_httpx_client", lambda: httpx.Client(transport=transport)
    ):
        result = downloader.download_url("https://example.com/x.onnx", target)

    assert result == target
    assert target.read_bytes() == b"MAIN"
    assert not (tmp_path / "x.onnx.json").exists()


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
