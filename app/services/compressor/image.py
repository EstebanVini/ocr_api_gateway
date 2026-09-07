import time
from io import BytesIO

from PIL import Image, ImageOps

from app.core.exceptions import CompressionFailedError
from app.services.compressor.base import CompressionResult, CompressionStrategy

_LOSSLESS_SOURCE_FORMATS = {"PNG", "BMP", "GIF", "TIFF"}
_JPEG_MAX_QUALITY = 95
_SCALE_STEP = 0.10


def _save(img: Image.Image, fmt: str, **kwargs: object) -> bytes:
    buf = BytesIO()
    img.save(buf, format=fmt, **kwargs)
    return buf.getvalue()


def _flatten_to_white(img: Image.Image) -> Image.Image:
    rgba = img.convert("RGBA")
    background = Image.new("RGB", rgba.size, (255, 255, 255))
    background.paste(rgba, mask=rgba.split()[-1])
    return background


def _binary_search_quality(
    img: Image.Image, max_bytes: int, *, low: int, high: int
) -> tuple[bytes, int] | None:
    """Finds the HIGHEST JPEG quality that still fits under max_bytes, or None if even
    `low` doesn't fit."""
    best: tuple[bytes, int] | None = None
    while low <= high:
        mid = (low + high) // 2
        candidate = _save(img, "JPEG", quality=mid, optimize=True, progressive=True, subsampling=0)
        if len(candidate) <= max_bytes:
            best = (candidate, mid)
            low = mid + 1
        else:
            high = mid - 1
    return best


def compress_image(
    data: bytes,
    *,
    max_bytes: int,
    min_quality: int,
    min_longest_side_px: int,
    min_scale_factor: float,
) -> CompressionResult:
    start = time.monotonic()

    if len(data) <= max_bytes:
        return CompressionResult(data=data, strategy=CompressionStrategy.NONE, was_compressed=False)

    opened = Image.open(BytesIO(data))
    original_format = opened.format
    img = ImageOps.exif_transpose(opened) or opened
    img.info.pop("exif", None)
    original_longest_side = max(img.size)

    if original_format in _LOSSLESS_SOURCE_FORMATS:
        out = _save(img, "PNG", optimize=True)
        if len(out) <= max_bytes:
            elapsed_ms = int((time.monotonic() - start) * 1000)
            return CompressionResult(
                data=out,
                strategy=CompressionStrategy.PNG_OPTIMIZE,
                was_compressed=True,
                elapsed_ms=elapsed_ms,
            )

    base = _flatten_to_white(img) if img.mode in ("RGBA", "LA", "P") else img.convert("RGB")
    floor_px = max(min_longest_side_px, min_scale_factor * original_longest_side)

    scale = 1.0
    last_attempt_data = b""
    last_attempt_quality = min_quality
    while True:
        candidate = (
            base
            if scale == 1.0
            else base.resize(
                (round(base.width * scale), round(base.height * scale)),
                Image.Resampling.LANCZOS,
            )
        )
        found = _binary_search_quality(
            candidate, max_bytes, low=min_quality, high=_JPEG_MAX_QUALITY
        )
        if found is not None:
            out, quality = found
            strategy = (
                CompressionStrategy.JPEG_QUALITY_SEARCH
                if scale == 1.0
                else CompressionStrategy.JPEG_QUALITY_SEARCH_SCALED
            )
            elapsed_ms = int((time.monotonic() - start) * 1000)
            return CompressionResult(
                data=out,
                strategy=strategy,
                was_compressed=True,
                quality=quality,
                scale_factor=scale,
                elapsed_ms=elapsed_ms,
            )

        last_attempt_data = _save(
            candidate, "JPEG", quality=min_quality, optimize=True, progressive=True, subsampling=0
        )
        last_attempt_quality = min_quality

        next_scale = round(scale - _SCALE_STEP, 2)
        if next_scale * original_longest_side < floor_px:
            break
        scale = next_scale

    raise CompressionFailedError(
        f"No se pudo comprimir la imagen por debajo de {max_bytes} bytes.",
        details={
            "original_size_bytes": len(data),
            "final_size_bytes": len(last_attempt_data),
            "strategy": CompressionStrategy.JPEG_QUALITY_SEARCH_SCALED.value,
            "last_parameter_tried": {"quality": last_attempt_quality, "scale_factor": scale},
        },
    )
