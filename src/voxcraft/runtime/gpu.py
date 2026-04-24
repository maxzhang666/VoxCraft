"""GPU 资源探测。

探测优先级：torch.cuda > pynvml > (0, 0/False)。
- torch 装了：直接用 torch.cuda，指标最准（还能区分 allocated 显存）
- torch 没装但 nvidia-ml-py 装了：走 driver 层查询，只能拿到进程外总占用
- 两者都没有：返回无 GPU
"""
from __future__ import annotations


def _torch_cuda():
    """返回 torch 模块；torch 未装或初始化失败返回 None。"""
    try:
        import torch  # type: ignore[import-not-found]
    except ImportError:
        return None
    # torch.cuda.is_available 首次调用会加载 CUDA runtime；失败时 torch 会打 warning 但不抛异常
    try:
        if torch.cuda.is_available():
            return torch
    except Exception:  # noqa: BLE001  —— 极端场景下 CUDA 初始化异常不应拖垮服务
        pass
    return None


def _nvml():
    """初始化并返回 pynvml 模块；失败返回 None。调用方自行 shutdown。"""
    try:
        import pynvml  # type: ignore[import-not-found]
    except ImportError:
        return None
    try:
        pynvml.nvmlInit()
        return pynvml
    except Exception:  # noqa: BLE001
        return None


def is_cuda_available() -> bool:
    if _torch_cuda() is not None:
        return True
    nvml = _nvml()
    if nvml is None:
        return False
    try:
        return nvml.nvmlDeviceGetCount() > 0
    except Exception:  # noqa: BLE001
        return False
    finally:
        try:
            nvml.nvmlShutdown()
        except Exception:  # noqa: BLE001
            pass


def empty_cache() -> None:
    torch = _torch_cuda()
    if torch is None:
        return
    try:
        torch.cuda.empty_cache()
    except Exception:  # noqa: BLE001
        pass


def vram_usage_mb() -> tuple[int, int]:
    """返回 (used_mb, total_mb)；无 GPU 时返回 (0, 0)。

    torch 路径：used = 本进程 allocated；total = 0 号卡总显存。
    pynvml 路径：used = 全局 used（driver 视角，含其他进程）；total = 0 号卡总显存。
    语义不完全一致，但前端仅展示总量占用趋势，不做进程级归因。
    """
    torch = _torch_cuda()
    if torch is not None:
        try:
            used = torch.cuda.memory_allocated() // (1024 * 1024)
            total = torch.cuda.get_device_properties(0).total_memory // (1024 * 1024)
            return (int(used), int(total))
        except Exception:  # noqa: BLE001
            return (0, 0)

    nvml = _nvml()
    if nvml is None:
        return (0, 0)
    try:
        handle = nvml.nvmlDeviceGetHandleByIndex(0)
        info = nvml.nvmlDeviceGetMemoryInfo(handle)
        return (int(info.used // (1024 * 1024)), int(info.total // (1024 * 1024)))
    except Exception:  # noqa: BLE001
        return (0, 0)
    finally:
        try:
            nvml.nvmlShutdown()
        except Exception:  # noqa: BLE001
            pass


def device_name() -> str | None:
    torch = _torch_cuda()
    if torch is not None:
        try:
            return torch.cuda.get_device_name(0)
        except Exception:  # noqa: BLE001
            return None

    nvml = _nvml()
    if nvml is None:
        return None
    try:
        handle = nvml.nvmlDeviceGetHandleByIndex(0)
        name = nvml.nvmlDeviceGetName(handle)
        # pynvml 新版本返回 str，老版本返回 bytes
        return name.decode() if isinstance(name, bytes) else str(name)
    except Exception:  # noqa: BLE001
        return None
    finally:
        try:
            nvml.nvmlShutdown()
        except Exception:  # noqa: BLE001
            pass
