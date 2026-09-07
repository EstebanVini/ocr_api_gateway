from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.config import Settings


class CompressionStrategy(str, Enum):
    NONE = "none"
    PNG_OPTIMIZE = "png_optimize"
    JPEG_QUALITY_SEARCH = "jpeg_quality_search"
    JPEG_QUALITY_SEARCH_SCALED = "jpeg_quality_search_scaled"
    PIKEPDF_LOSSLESS = "pikepdf_lossless"
    PYMUPDF_REWRITE = "pymupdf_rewrite"
    PDF_RASTERIZE = "pdf_rasterize"


@dataclass
class CompressionResult:
    data: bytes
    strategy: CompressionStrategy
    was_compressed: bool
    quality: int | None = None
    scale_factor: float | None = None
    dpi: int | None = None
    elapsed_ms: int = 0


def compress_if_needed(
    data: bytes, ocr_space_filetype: str, settings: "Settings"
) -> CompressionResult:
    """Orchestrates compression: passthrough if already under the threshold, otherwise
    dispatches to the image or PDF compressor depending on the detected type."""
    from app.services.compressor.image import compress_image
    from app.services.compressor.pdf import compress_pdf

    if ocr_space_filetype == "PDF":
        return compress_pdf(
            data, max_bytes=settings.ocr_max_upload_bytes, min_dpi=settings.ocr_min_pdf_dpi
        )
    return compress_image(
        data,
        max_bytes=settings.ocr_max_upload_bytes,
        min_quality=settings.ocr_min_jpeg_quality,
        min_longest_side_px=settings.ocr_min_image_longest_side_px,
        min_scale_factor=settings.ocr_min_image_scale_factor,
    )
