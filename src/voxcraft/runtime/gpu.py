"""GPU 资源工具。torch 软依赖：不可用时全部退化为 no-op / 0。"""
from __future__ import annotations


def is_cuda_available() -> bool:
    try:
        import torch  # type: ignore[import-not-found]

        return bool(torch.cuda.is_available())
    except ImportError:
        return False


def empty_cache() -> None:
    try:
        import torch  # type: ignore[import-not-found]

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except ImportError:
        pass


def vram_usage_mb() -> tuple[int, int]:
    """返回 (used_mb, total_mb)；无 CUDA 时返回 (0, 0)。"""
    try:
        import torch  # type: ignore[import-not-found]

        if not torch.cuda.is_available():
            return (0, 0)
        used = torch.cuda.memory_allocated() // (1024 * 1024)
        total = torch.cuda.get_device_properties(0).total_memory // (1024 * 1024)
        return (int(used), int(total))
    except ImportError:
        return (0, 0)


def device_name() -> str | None:
    try:
        import torch  # type: ignore[import-not-found]

        if not torch.cuda.is_available():
            return None
        return torch.cuda.get_device_name(0)
    except ImportError:
        return None
