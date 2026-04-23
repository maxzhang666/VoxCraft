"""GPU 工具烟雾测试：torch 不可用时退化为安全默认值。"""
from __future__ import annotations

from voxcraft.runtime import gpu


def test_is_cuda_available_returns_bool():
    assert isinstance(gpu.is_cuda_available(), bool)


def test_empty_cache_is_safe_without_cuda():
    gpu.empty_cache()  # 不应抛异常


def test_vram_usage_returns_tuple():
    used, total = gpu.vram_usage_mb()
    assert isinstance(used, int)
    assert isinstance(total, int)
    assert used >= 0
    assert total >= 0


def test_device_name_returns_str_or_none():
    r = gpu.device_name()
    assert r is None or isinstance(r, str)
