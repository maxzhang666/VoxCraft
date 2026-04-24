"""VoxCraft 全局异常层次。所有业务异常继承自 VoxCraftError。"""
from __future__ import annotations


class VoxCraftError(Exception):
    """业务异常基类。子类覆盖 default_code / default_status。"""

    default_code: str = "INTERNAL_ERROR"
    default_status: int = 500

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        status_code: int | None = None,
        details: dict | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code or self.default_code
        self.status_code = status_code or self.default_status
        self.details = details

    def __str__(self) -> str:
        return f"[{self.code}] {self.message}"


# --- Provider 层 ---

class ProviderError(VoxCraftError):
    default_code = "PROVIDER_ERROR"


class ModelLoadError(ProviderError):
    default_code = "MODEL_LOAD_ERROR"


class InferenceError(ProviderError):
    default_code = "INFERENCE_ERROR"


# --- 资源 ---

class ResourceExhausted(VoxCraftError):
    """GPU OOM、磁盘满等。"""
    default_code = "RESOURCE_EXHAUSTED"
    default_status = 503


# --- 校验 ---

class ValidationError(VoxCraftError):
    default_code = "VALIDATION_ERROR"
    default_status = 400


# --- 配置 ---

class ConfigError(VoxCraftError):
    default_code = "CONFIG_ERROR"


# --- 模型管理（v0.1.2 / ADR-010）---

class DownloadError(VoxCraftError):
    """模型下载失败（网络 / 源 / 依赖缺失）。"""
    default_code = "DOWNLOAD_FAILED"


class ModelNotReadyError(VoxCraftError):
    """Provider 尝试引用未 ready 的 Model。"""
    default_code = "MODEL_NOT_READY"
    default_status = 409


class ModelInUseError(VoxCraftError):
    """尝试删除仍被 Provider 引用的 Model。"""
    default_code = "MODEL_IN_USE"
    default_status = 409


class CatalogKeyConflictError(VoxCraftError):
    """自定义 key 冲突内置 catalog 或保留前缀。"""
    default_code = "CATALOG_KEY_CONFLICT"
    default_status = 400


# --- LLM 接入（v0.3.0）---

class LlmNotConfiguredError(VoxCraftError):
    """未配置任何 LLM Provider，或指名 Provider 不存在。"""
    default_code = "LLM_NOT_CONFIGURED"
    default_status = 400


class LlmApiError(VoxCraftError):
    """LLM API 调用失败（网络 / 鉴权 / 模型不存在 / 等）。"""
    default_code = "LLM_API_ERROR"
    default_status = 502


# --- 视频翻译编排（v0.4.0 / ADR-014）---

class MediaDecodeError(VoxCraftError):
    """ffmpeg probe / demux / mux 失败（编码不支持 / 文件损坏）。"""
    default_code = "MEDIA_DECODE_ERROR"
    default_status = 422


class InvalidMediaError(VoxCraftError):
    """上传文件类型不在支持列表内。"""
    default_code = "INVALID_MEDIA"
    default_status = 422


class UploadTooLargeError(VoxCraftError):
    """上传文件超 VOXCRAFT_MAX_UPLOAD_SIZE。"""
    default_code = "UPLOAD_TOO_LARGE"
    default_status = 422


class CloneNotSupportedError(VoxCraftError):
    """clone_voice=true 但显式指定的 TTS Provider 不支持克隆。"""
    default_code = "CLONE_NOT_SUPPORTED"
    default_status = 422


class CloneNotSupportedDefaultError(VoxCraftError):
    """clone_voice=true 且默认 TTS 不支持克隆；拒绝自动降级，要求显式指定。"""
    default_code = "CLONE_NOT_SUPPORTED_DEFAULT"
    default_status = 422


class CloneRefInvalidError(VoxCraftError):
    """克隆参考音频不达标（过短 / 过静）。"""
    default_code = "CLONE_REF_INVALID"
    default_status = 422


class InvalidLangError(VoxCraftError):
    """target_lang / source_lang 不在支持列表。"""
    default_code = "INVALID_LANG"
    default_status = 422
