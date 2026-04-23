"""模型下载器（v0.1.2 / ADR-010）。

四个分支：
- download_hf(repo_id, local_dir)       HuggingFace（max_workers 多线程）
- download_ms(repo_id, local_dir)       ModelScope
- download_url(url, local_path)         直连 HTTP 下载（Piper 等单文件）
- download_torch_hub(name, local_dir)   torch.hub 特殊路径（Demucs）

全部为**同步阻塞**调用；上层 ModelDownloadService 在 executor 中调度并
通过后台扫描目录大小实现进度回调（ADR-010 备路径方案）。
"""
from __future__ import annotations

from pathlib import Path

import httpx
from huggingface_hub import snapshot_download as hf_snapshot_download

from voxcraft.errors import DownloadError

# 延迟 import 由各分支内做；顶层只保留 hf（faster-whisper 已带）
try:
    from modelscope import snapshot_download as ms_snapshot_download
except ImportError:  # 允许环境未装 modelscope 时仍能 import 本模块
    ms_snapshot_download = None  # type: ignore[assignment]


_CHUNK_SIZE = 1024 * 1024  # 1 MiB


def _build_httpx_client() -> httpx.Client:
    """工厂函数方便测试 mock。"""
    return httpx.Client(follow_redirects=True, timeout=None)


def download_hf(
    repo_id: str,
    local_dir: Path,
    max_workers: int = 8,
) -> Path:
    local_dir = Path(local_dir)
    local_dir.mkdir(parents=True, exist_ok=True)
    try:
        hf_snapshot_download(
            repo_id=repo_id,
            local_dir=str(local_dir),
            max_workers=max_workers,
        )
    except Exception as e:
        raise DownloadError(
            f"HuggingFace download failed: {e}",
            details={"repo_id": repo_id, "source": "hf"},
        ) from e
    return local_dir


def download_ms(
    repo_id: str,
    local_dir: Path,
    max_workers: int = 8,
) -> Path:
    if ms_snapshot_download is None:
        raise DownloadError(
            "modelscope not installed",
            details={"repo_id": repo_id, "source": "ms"},
        )
    local_dir = Path(local_dir)
    local_dir.mkdir(parents=True, exist_ok=True)
    try:
        ms_snapshot_download(
            model_id=repo_id,
            local_dir=str(local_dir),
            max_workers=max_workers,
        )
    except Exception as e:
        raise DownloadError(
            f"ModelScope download failed: {e}",
            details={"repo_id": repo_id, "source": "ms"},
        ) from e
    return local_dir


def download_url(url: str, local_path: Path) -> Path:
    local_path = Path(local_path)
    local_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        client = _build_httpx_client()
        try:
            with client.stream("GET", url) as r:
                r.raise_for_status()
                with local_path.open("wb") as f:
                    for chunk in r.iter_bytes(chunk_size=_CHUNK_SIZE):
                        f.write(chunk)
        finally:
            client.close()
    except httpx.HTTPStatusError as e:
        raise DownloadError(
            f"URL download HTTP error: {e.response.status_code}",
            details={"url": url, "source": "url"},
        ) from e
    except Exception as e:
        raise DownloadError(
            f"URL download failed: {e}",
            details={"url": url, "source": "url"},
        ) from e
    return local_path


def download_torch_hub(model_name: str, local_dir: Path) -> Path:
    """Demucs 等通过 torch.hub 管理的模型。

    torch.hub 自己维护 cache（~/.cache/torch/hub/），这里仅触发下载并在
    local_dir 写一个 marker 文件，保持与其他 Provider 一致的"已就绪"语义。
    """
    try:
        import torch.hub  # noqa: F401
    except ImportError as e:
        raise DownloadError(
            "torch not installed (demucs / torch.hub download requires it)",
            details={"model": model_name, "source": "torch_hub"},
        ) from e
    try:
        from demucs.pretrained import get_model  # type: ignore[import-not-found]
    except ImportError as e:
        raise DownloadError(
            "demucs not installed; run `pip install demucs` first",
            details={"model": model_name, "source": "torch_hub"},
        ) from e

    local_dir = Path(local_dir)
    local_dir.mkdir(parents=True, exist_ok=True)
    try:
        get_model(model_name)
    except Exception as e:
        raise DownloadError(
            f"torch.hub download failed: {e}",
            details={"model": model_name, "source": "torch_hub"},
        ) from e
    (local_dir / "torch_hub.marker").write_text(f"model={model_name}\n")
    return local_dir
