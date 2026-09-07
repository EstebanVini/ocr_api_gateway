from collections.abc import Mapping
from typing import Any, ClassVar

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import get_logger
from app.models.errors import ErrorCode, ErrorDetail, ErrorResponse

logger = get_logger(__name__)


class ServiceError(Exception):
    """Base class for all service-level errors that map to a documented HTTP response."""

    error_code: ClassVar[ErrorCode] = ErrorCode.INTERNAL_ERROR
    http_status: ClassVar[int] = status.HTTP_500_INTERNAL_SERVER_ERROR

    def __init__(self, message: str, *, details: Mapping[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = dict(details) if details else {}


class UnsupportedFileTypeError(ServiceError):
    error_code = ErrorCode.UNSUPPORTED_FILE_TYPE
    http_status = status.HTTP_415_UNSUPPORTED_MEDIA_TYPE


class RawInputTooLargeError(ServiceError):
    error_code = ErrorCode.FILE_TOO_LARGE
    http_status = status.HTTP_413_CONTENT_TOO_LARGE


class CompressionFailedError(ServiceError):
    error_code = ErrorCode.COMPRESSION_FAILED
    http_status = status.HTTP_413_CONTENT_TOO_LARGE


class PdfPageLimitExceededError(ServiceError):
    error_code = ErrorCode.PDF_PAGE_LIMIT_EXCEEDED
    http_status = status.HTTP_422_UNPROCESSABLE_CONTENT


class CorruptOrEncryptedFileError(ServiceError):
    error_code = ErrorCode.CORRUPT_OR_ENCRYPTED_FILE
    http_status = status.HTTP_422_UNPROCESSABLE_CONTENT


class OcrSpaceError(ServiceError):
    error_code = ErrorCode.OCR_SPACE_ERROR
    http_status = status.HTTP_502_BAD_GATEWAY


class OcrSpaceAuthError(OcrSpaceError):
    error_code = ErrorCode.OCR_SPACE_AUTH_ERROR


class OcrSpaceInvalidResponseError(OcrSpaceError):
    error_code = ErrorCode.OCR_SPACE_INVALID_RESPONSE


def _error_json(error_code: ErrorCode, message: str, details: dict[str, Any]) -> dict[str, Any]:
    return ErrorResponse(
        error=ErrorDetail(code=error_code, message=message, details=details)
    ).model_dump(mode="json")


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(ServiceError)
    async def _handle_service_error(request: Request, exc: ServiceError) -> JSONResponse:
        logger.warning(
            "service_error",
            code=exc.error_code.value,
            http_status=exc.http_status,
            path=request.url.path,
            **exc.details,
        )
        return JSONResponse(
            status_code=exc.http_status,
            content=_error_json(exc.error_code, exc.message, exc.details),
        )

    @app.exception_handler(RequestValidationError)
    async def _handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        logger.warning("validation_error", path=request.url.path, errors=exc.errors())
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content=_error_json(
                ErrorCode.VALIDATION_ERROR,
                "La peticion no cumple con el formato esperado.",
                {"errors": exc.errors()},
            ),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _handle_http_exception(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        logger.warning(
            "http_exception", path=request.url.path, status_code=exc.status_code, detail=exc.detail
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_json(ErrorCode.INTERNAL_ERROR, str(exc.detail), {}),
        )

    @app.exception_handler(Exception)
    async def _handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled_error", path=request.url.path)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=_error_json(
                ErrorCode.INTERNAL_ERROR, "Ocurrio un error interno inesperado.", {}
            ),
        )
