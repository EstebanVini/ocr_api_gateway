from enum import IntEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class OCRExitCode(IntEnum):
    SUCCESS = 1
    PARTIAL_SUCCESS = 2
    PARSE_FAILED = 3
    FATAL_ERROR = 4


class FileParseExitCode(IntEnum):
    FILE_NOT_FOUND = 0
    SUCCESS = 1
    OCR_ENGINE_PARSE_ERROR = -10
    TIMEOUT = -20
    VALIDATION_ERROR = -30
    UNKNOWN_ERROR = -99


class CompressionInfo(BaseModel):
    strategy: str
    quality: int | None = None
    scale_factor: float | None = None
    dpi: int | None = None
    elapsed_ms: int


class FileInfo(BaseModel):
    filename: str
    detected_type: str
    mime_type: str
    original_size_bytes: int
    sent_size_bytes: int
    was_compressed: bool
    compression: CompressionInfo | None = None


class RequestEcho(BaseModel):
    language: str
    ocr_engine: int
    detect_orientation: bool
    searchable_pdf: bool


class OverlayWord(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    word_text: str = Field(alias="WordText")
    left: float = Field(alias="Left")
    top: float = Field(alias="Top")
    height: float = Field(alias="Height")
    width: float = Field(alias="Width")


class OverlayLine(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    words: list[OverlayWord] = Field(alias="Words")
    line_text: str = Field(alias="LineText")


class Overlay(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    lines: list[OverlayLine] = Field(alias="Lines")


class PageResult(BaseModel):
    page: int
    exit_code: int
    exit_status: str
    text: str
    error_message: str | None = None
    overlay: Overlay | None = None


class OcrResult(BaseModel):
    exit_code: int
    exit_status: str
    processing_time_ms: int
    text_orientation: str
    page_count: int
    text: str
    pages: list[PageResult]
    searchable_pdf_url: str | None = None


class OcrResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "success": True,
                "file": {
                    "filename": "pasaporte.jpg",
                    "detected_type": "JPG",
                    "mime_type": "image/jpeg",
                    "original_size_bytes": 3241984,
                    "sent_size_bytes": 987432,
                    "was_compressed": True,
                    "compression": {
                        "strategy": "jpeg_quality_search",
                        "quality": 78,
                        "scale_factor": 0.9,
                        "dpi": None,
                        "elapsed_ms": 412,
                    },
                },
                "request": {
                    "language": "spa",
                    "ocr_engine": 2,
                    "detect_orientation": True,
                    "searchable_pdf": False,
                },
                "ocr": {
                    "exit_code": 1,
                    "exit_status": "SUCCESS",
                    "processing_time_ms": 3000,
                    "text_orientation": "0",
                    "page_count": 1,
                    "text": "texto completo concatenado con \n entre paginas",
                    "pages": [
                        {
                            "page": 1,
                            "exit_code": 1,
                            "exit_status": "SUCCESS",
                            "text": "texto de la pagina",
                            "error_message": None,
                            "overlay": None,
                        }
                    ],
                    "searchable_pdf_url": None,
                },
                "raw": None,
            }
        }
    )

    success: Literal[True] = True
    file: FileInfo
    request: RequestEcho
    ocr: OcrResult
    raw: dict[str, Any] | None = None


class LimitsResponse(BaseModel):
    max_upload_bytes: int
    max_pdf_pages: int
    max_input_bytes: int
    min_jpeg_quality: int
    min_pdf_dpi: int
    timeout_seconds: float
