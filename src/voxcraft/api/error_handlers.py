"""VoxCraftError → 统一错误响应体。"""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from voxcraft.errors import VoxCraftError


async def voxcraft_error_handler(
    request: Request, exc: VoxCraftError
) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": exc.code,
                "message": exc.message,
                "details": exc.details,
            }
        },
    )


async def validation_error_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    return JSONResponse(
        status_code=400,
        content={
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "Request validation failed",
                "details": {"errors": exc.errors()},
            }
        },
    )


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(VoxCraftError, voxcraft_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
