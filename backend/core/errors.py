"""Structured API errors and FastAPI exception handlers."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class AppError(Exception):
    status_code: int = 500
    error_code: str = "internal_error"

    def __init__(self, message: str, details: dict | None = None) -> None:
        self.message = message
        self.details = details or {}
        super().__init__(message)


class RepositoryNotFoundError(AppError):
    status_code = 404
    error_code = "repository_not_found"


class JobNotFoundError(AppError):
    status_code = 404
    error_code = "job_not_found"


class ChatNotFoundError(AppError):
    status_code = 404
    error_code = "chat_not_found"


class BookmarkNotFoundError(AppError):
    status_code = 404
    error_code = "bookmark_not_found"


class AnalysisNotReadyError(AppError):
    status_code = 409
    error_code = "analysis_not_ready"


class InvalidUploadError(AppError):
    status_code = 400
    error_code = "invalid_upload"


class StorageError(AppError):
    status_code = 500
    error_code = "storage_error"


class ValidationAppError(AppError):
    status_code = 422
    error_code = "validation_error"


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def app_error_handler(_request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": exc.error_code,
                "message": exc.message,
                "details": exc.details,
            },
        )

    @app.exception_handler(Exception)
    async def unhandled_error_handler(_request: Request, _exc: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=500,
            content={
                "error": "internal_error",
                "message": "An unexpected error occurred.",
                "details": {},
            },
        )
