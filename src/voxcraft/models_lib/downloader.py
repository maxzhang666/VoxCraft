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

import os
import time
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import httpx
import structlog
from huggingface_hub import snapshot_download as hf_snapshot_download

from voxcraft.errors import DownloadError

log = structlog.get_logger()


def _rewrite_hf_url_for_mirror(url: str) -> str:
    """若 URL 指向 huggingface.co 且配置了 HF_ENDPOINT 镜像，把 host 替换过去。

    catalog 中 Piper 等单文件模型 URL 是硬编码的 https://huggingface.co/... 形式，
    走 httpx 直连，不经过 huggingface_hub SDK；HF_ENDPOINT env 对它无效。
    本函数把 host 重写到镜像（如 https://hf-mirror.com），保留 path/query/fragment。
    主流 HF 镜像（hf-mirror.com 等）都按相同 path 结构对齐，所以重写安全。
    """
    endpoint = (os.environ.get("HF_ENDPOINT") or "").strip()
    if not endpoint:
        return url
    src = urlparse(url)
    if not src.netloc.endswith("huggingface.co"):
        return url
    mirror = urlparse(endpoint.rstrip("/"))
    if not mirror.netloc:
        return url
    return urlunparse((
        mirror.scheme or src.scheme,
        mirror.netloc,
        src.path,
        src.params,
        src.query,
        src.fragment,
    ))

# 延迟 import 由各分支内做；顶层只保留 hf（faster-whisper 已带）
try:
    from modelscope import snapshot_download as ms_snapshot_download
except ImportError:  # 允许环境未装 modelscope 时仍能 import 本模块
    ms_snapshot_download = None  # type: ignore[assignment]


_CHUNK_SIZE = 1024 * 1024  # 1 MiB


def _build_httpx_client() -> httpx.Client:
    """工厂函数方便测试 mock。trust_env=True 让 httpx 自动遵循 HTTPS_PROXY/HTTP_PROXY/NO_PROXY。"""
    return httpx.Client(follow_redirects=True, timeout=None, trust_env=True)


def download_hf(
    repo_id: str,
    local_dir: Path,
    max_workers: int = 8,
) -> Path:
    local_dir = Path(local_dir)
    local_dir.mkdir(parents=True, exist_ok=True)

    # huggingface_hub 在 import 时把 HF_ENDPOINT 固化为模块常量；
    # 运行时改 env 不会影响已 import 的引用。这里每次显式从 env 读出来传入，
    # 让 UI 改完代理无需重启容器即可生效。
    endpoint = (os.environ.get("HF_ENDPOINT") or "").strip() or None
    https_proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy") or None
    http_proxy = os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy") or None

    log.info(
        "download.hf.start",
        repo_id=repo_id,
        local_dir=str(local_dir),
        endpoint=endpoint or "https://huggingface.co (default)",
        https_proxy=https_proxy,
        http_proxy=http_proxy,
        max_workers=max_workers,
    )
    started = time.monotonic()
    try:
        hf_snapshot_download(
            repo_id=repo_id,
            local_dir=str(local_dir),
            max_workers=max_workers,
            endpoint=endpoint,
        )
    except Exception as e:
        log.error(
            "download.hf.failed",
            repo_id=repo_id,
            endpoint=endpoint,
            error_type=type(e).__name__,
            error_msg=str(e),
            exc_info=True,
        )
        raise DownloadError(
            f"HuggingFace download failed: {e}",
            details={"repo_id": repo_id, "source": "hf", "endpoint": endpoint},
        ) from e
    log.info(
        "download.hf.done",
        repo_id=repo_id,
        elapsed_s=round(time.monotonic() - started, 2),
    )
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

    log.info(
        "download.ms.start",
        repo_id=repo_id,
        local_dir=str(local_dir),
        max_workers=max_workers,
    )
    started = time.monotonic()
    try:
        ms_snapshot_download(
            model_id=repo_id,
            local_dir=str(local_dir),
            max_workers=max_workers,
        )
    except Exception as e:
        log.error(
            "download.ms.failed",
            repo_id=repo_id,
            error_type=type(e).__name__,
            error_msg=str(e),
            exc_info=True,
        )
        raise DownloadError(
            f"ModelScope download failed: {e}",
            details={"repo_id": repo_id, "source": "ms"},
        ) from e
    log.info(
        "download.ms.done",
        repo_id=repo_id,
        elapsed_s=round(time.monotonic() - started, 2),
    )
    return local_dir


def download_url(url: str, local_path: Path) -> Path:
    """下载单个 URL 到 local_path。

    Piper 约定：`.onnx` 模型必须配对同目录同名的 `.onnx.json` 配置才能 load。
    catalog 只挂了主 URL 时，本函数会自动下 sidecar JSON（URL + `.json`），
    sidecar 失败不致命（已日志，不抛错），但 Provider 加载时仍会报错——这是
    正确的失败点，因为主模型文件没有配置时本就不可用。
    """
    local_path = Path(local_path)
    local_path.parent.mkdir(parents=True, exist_ok=True)
    rewritten = _rewrite_hf_url_for_mirror(url)
    if rewritten != url:
        log.info(
            "download.url.hf_mirror_rewrite",
            original=url,
            rewritten=rewritten,
        )
    _download_single(rewritten, local_path)
    if url.endswith(".onnx"):
        # sidecar 也走重写后的镜像（如果原 URL 触发了重写）
        sidecar_src = rewritten + ".json"
        sidecar_path = local_path.parent / (local_path.name + ".json")
        try:
            _download_single(sidecar_src, sidecar_path)
        except DownloadError:
            # 记一下，不拉起失败；Provider 载入时若真缺 sidecar 会给出准确错误
            import logging
            logging.getLogger(__name__).warning(
                "piper sidecar not found: %s (provider load will fail)", sidecar_src,
            )
    return local_path


def _download_single(url: str, local_path: Path) -> None:
    https_proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy") or None
    log.info(
        "download.url.start",
        url=url,
        local_path=str(local_path),
        https_proxy=https_proxy,
    )
    started = time.monotonic()
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
        log.error(
            "download.url.failed",
            url=url,
            status=e.response.status_code,
            error_msg=str(e),
        )
        raise DownloadError(
            f"URL download HTTP error: {e.response.status_code}",
            details={"url": url, "source": "url"},
        ) from e
    except Exception as e:
        log.error(
            "download.url.failed",
            url=url,
            error_type=type(e).__name__,
            error_msg=str(e),
            exc_info=True,
        )
        raise DownloadError(
            f"URL download failed: {e}",
            details={"url": url, "source": "url"},
        ) from e
    log.info(
        "download.url.done",
        url=url,
        elapsed_s=round(time.monotonic() - started, 2),
    )


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
    log.info("download.torch_hub.start", model=model_name, local_dir=str(local_dir))
    started = time.monotonic()
    try:
        get_model(model_name)
    except Exception as e:
        log.error(
            "download.torch_hub.failed",
            model=model_name,
            error_type=type(e).__name__,
            error_msg=str(e),
            exc_info=True,
        )
        raise DownloadError(
            f"torch.hub download failed: {e}",
            details={"model": model_name, "source": "torch_hub"},
        ) from e
    (local_dir / "torch_hub.marker").write_text(f"model={model_name}\n")
    log.info(
        "download.torch_hub.done",
        model=model_name,
        elapsed_s=round(time.monotonic() - started, 2),
    )
    return local_dir
