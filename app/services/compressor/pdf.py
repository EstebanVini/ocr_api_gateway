import time
from io import BytesIO

import fitz
import pikepdf
from PIL import Image

from app.core.exceptions import (
    CompressionFailedError,
    CorruptOrEncryptedFileError,
    PdfPageLimitExceededError,
)
from app.services.compressor.base import CompressionResult, CompressionStrategy

_RASTER_DPI_CASCADE = (300, 250, 200, 150)
_RASTER_JPEG_QUALITY = 80
_IMAGE_RECOMPRESS_THRESHOLD_BYTES = 200_000


def _open_pikepdf(data: bytes) -> pikepdf.Pdf:
    try:
        return pikepdf.open(BytesIO(data))
    except pikepdf.PasswordError as exc:
        raise CorruptOrEncryptedFileError(
            "El PDF esta protegido con contrasena y no puede procesarse.", details={}
        ) from exc
    except pikepdf.PdfError as exc:
        raise CorruptOrEncryptedFileError(
            "El PDF esta corrupto o no pudo abrirse.", details={}
        ) from exc


def validate_page_count(data: bytes, max_pages: int) -> int:
    with _open_pikepdf(data) as pdf:
        page_count = len(pdf.pages)

    if page_count > max_pages:
        raise PdfPageLimitExceededError(
            f"El plan actual de OCR.space acepta máximo {max_pages} páginas; "
            f"el PDF tiene {page_count}",
            details={"page_count": page_count, "max_pages": max_pages},
        )
    return page_count


def _pikepdf_lossless(data: bytes) -> bytes:
    buf = BytesIO()
    with _open_pikepdf(data) as pdf:
        pdf.save(
            buf,
            compress_streams=True,
            object_stream_mode=pikepdf.ObjectStreamMode.generate,
            linearize=False,
        )
    return buf.getvalue()


def _open_fitz(data: bytes) -> fitz.Document:
    try:
        return fitz.open(stream=data, filetype="pdf")
    except fitz.FileDataError as exc:
        raise CorruptOrEncryptedFileError(
            "El PDF esta corrupto o no pudo abrirse.", details={}
        ) from exc


def _pymupdf_rewrite(data: bytes, *, image_size_threshold_bytes: int) -> bytes:
    doc = _open_fitz(data)
    try:
        for page in doc:
            for image_info in page.get_images(full=True):
                xref = image_info[0]
                try:
                    extracted = doc.extract_image(xref)
                    image_bytes = extracted["image"]
                    if len(image_bytes) <= image_size_threshold_bytes:
                        continue
                    pil_img = Image.open(BytesIO(image_bytes)).convert("RGB")
                    out_buf = BytesIO()
                    pil_img.save(out_buf, format="JPEG", quality=70, optimize=True)
                    page.replace_image(xref, stream=out_buf.getvalue())
                except Exception:  # noqa: BLE001 - best-effort per-image recompression
                    continue
        buf = BytesIO()
        doc.save(buf, garbage=4, deflate=True, clean=True)
        return buf.getvalue()
    finally:
        doc.close()


def _rasterize_to_pdf(data: bytes, *, dpi: int, jpeg_quality: int) -> bytes:
    src = _open_fitz(data)
    out = fitz.open()
    try:
        zoom = dpi / 72
        matrix = fitz.Matrix(zoom, zoom)
        for src_page in src:
            pix = src_page.get_pixmap(matrix=matrix, alpha=False)
            jpeg_bytes = pix.tobytes("jpeg", jpg_quality=jpeg_quality)
            page_width_pt = pix.width * 72 / dpi
            page_height_pt = pix.height * 72 / dpi
            new_page = out.new_page(width=page_width_pt, height=page_height_pt)
            new_page.insert_image(new_page.rect, stream=jpeg_bytes)
        buf = BytesIO()
        out.save(buf)
        return buf.getvalue()
    finally:
        src.close()
        out.close()


def compress_pdf(data: bytes, *, max_bytes: int, min_dpi: int) -> CompressionResult:
    start = time.monotonic()

    if len(data) <= max_bytes:
        return CompressionResult(data=data, strategy=CompressionStrategy.NONE, was_compressed=False)

    out = _pikepdf_lossless(data)
    if len(out) <= max_bytes:
        return CompressionResult(
            data=out,
            strategy=CompressionStrategy.PIKEPDF_LOSSLESS,
            was_compressed=True,
            elapsed_ms=int((time.monotonic() - start) * 1000),
        )

    out = _pymupdf_rewrite(data, image_size_threshold_bytes=_IMAGE_RECOMPRESS_THRESHOLD_BYTES)
    if len(out) <= max_bytes:
        return CompressionResult(
            data=out,
            strategy=CompressionStrategy.PYMUPDF_REWRITE,
            was_compressed=True,
            elapsed_ms=int((time.monotonic() - start) * 1000),
        )

    last_data = out
    last_dpi = _RASTER_DPI_CASCADE[0]
    for dpi in (d for d in _RASTER_DPI_CASCADE if d >= min_dpi):
        last_data = _rasterize_to_pdf(data, dpi=dpi, jpeg_quality=_RASTER_JPEG_QUALITY)
        last_dpi = dpi
        if len(last_data) <= max_bytes:
            return CompressionResult(
                data=last_data,
                strategy=CompressionStrategy.PDF_RASTERIZE,
                was_compressed=True,
                dpi=dpi,
                elapsed_ms=int((time.monotonic() - start) * 1000),
            )

    raise CompressionFailedError(
        f"No se pudo comprimir el PDF por debajo de {max_bytes} bytes.",
        details={
            "original_size_bytes": len(data),
            "final_size_bytes": len(last_data),
            "strategy": CompressionStrategy.PDF_RASTERIZE.value,
            "last_parameter_tried": {"dpi": last_dpi},
        },
    )
