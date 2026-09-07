from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class ErrorCode(str, Enum):
    UNSUPPORTED_FILE_TYPE = "UNSUPPORTED_FILE_TYPE"
    FILE_TOO_LARGE = "FILE_TOO_LARGE"
    COMPRESSION_FAILED = "COMPRESSION_FAILED"
    PDF_PAGE_LIMIT_EXCEEDED = "PDF_PAGE_LIMIT_EXCEEDED"
    CORRUPT_OR_ENCRYPTED_FILE = "CORRUPT_OR_ENCRYPTED_FILE"
    OCR_SPACE_ERROR = "OCR_SPACE_ERROR"
    OCR_SPACE_AUTH_ERROR = "OCR_SPACE_AUTH_ERROR"
    OCR_SPACE_INVALID_RESPONSE = "OCR_SPACE_INVALID_RESPONSE"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    MISSING_API_KEY = "MISSING_API_KEY"
    INVALID_API_KEY = "INVALID_API_KEY"
    RATE_LIMIT_EXCEEDED = "RATE_LIMIT_EXCEEDED"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class ErrorDetail(BaseModel):
    code: ErrorCode
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    success: Literal[False] = False
    error: ErrorDetail
