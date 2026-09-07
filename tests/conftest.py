import os
from collections.abc import Iterator
from io import BytesIO

import fitz
import pytest
from PIL import Image

# Must be set before any test module imports app.main (which builds Settings at
# import time), and that import can happen during collection, before fixtures run.
os.environ.setdefault("OCR_SPACE_API_KEY", "test-api-key")


@pytest.fixture(autouse=True)
def _env_setup(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("OCR_SPACE_API_KEY", "test-api-key")
    from app.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def make_image_bytes(
    fmt: str,
    size: tuple[int, int] = (20, 20),
    color: tuple[int, int, int] = (200, 30, 30),
    **save_kwargs: object,
) -> bytes:
    """Minimal valid image in the given Pillow format (PNG/JPEG/GIF/BMP/TIFF)."""
    img = Image.new("RGB", size, color)
    buf = BytesIO()
    img.save(buf, format=fmt, **save_kwargs)
    return buf.getvalue()


def make_pdf_bytes(n_pages: int = 1, page_size: tuple[float, float] = (200, 200)) -> bytes:
    """Minimal valid multi-page PDF built with PyMuPDF."""
    doc = fitz.open()
    for _ in range(n_pages):
        doc.new_page(width=page_size[0], height=page_size[1])
    data = doc.tobytes()
    doc.close()
    return data


def make_corrupt_pdf_bytes() -> bytes:
    """Bytes with a valid %PDF- magic header but an unparseable body.

    A merely-truncated PDF is silently repaired by both pikepdf and PyMuPDF's xref
    recovery, so it doesn't exercise the corrupt-file error path. This does.
    """
    return b"%PDF-1.4\n" + bytes(i % 256 for i in range(2000))


def make_low_entropy_png_bytes(size: tuple[int, int] = (1200, 1200)) -> bytes:
    """A smooth gradient saved with zero compression: large raw bytes, but shrinks
    drastically under PNG optimize=True (exercises the lossless PNG_OPTIMIZE path)."""
    base = Image.linear_gradient("L").resize(size)
    img = base.convert("RGB")
    buf = BytesIO()
    img.save(buf, format="PNG", optimize=False, compress_level=0)
    return buf.getvalue()


def make_high_entropy_image_bytes(
    size: tuple[int, int] = (2200, 2200), sigma: float = 60, fmt: str = "PNG"
) -> bytes:
    """Random noise: resists lossless compression, forces the JPEG quality/scale
    search path. Saved as PNG (a lossless source format) so the compressor's
    PNG_OPTIMIZE attempt is exercised first and fails, as it would for a real photo."""
    noise = Image.effect_noise(size, sigma).convert("RGB")
    buf = BytesIO()
    noise.save(buf, format=fmt)
    return buf.getvalue()


def make_transparent_image(size: tuple[int, int] = (40, 40)) -> Image.Image:
    """RGBA image with a fully transparent corner, for flatten-to-white testing."""
    img = Image.new("RGBA", size, (10, 20, 30, 255))
    for x in range(size[0] // 2):
        for y in range(size[1] // 2):
            img.putpixel((x, y), (10, 20, 30, 0))
    return img


def make_exif_rotated_jpeg_bytes(size: tuple[int, int] = (40, 20)) -> bytes:
    """A JPEG with an EXIF Orientation tag requiring a 90-degree rotation."""
    img = Image.new("RGB", size, (0, 0, 255))
    exif = Image.Exif()
    exif[0x0112] = 6  # Orientation: rotate 90 CW
    buf = BytesIO()
    img.save(buf, format="JPEG", exif=exif.tobytes(), quality=95)
    return buf.getvalue()


def make_pdf_with_large_embedded_image_bytes(
    n_pages: int = 1, image_size: tuple[int, int] = (1600, 1600)
) -> bytes:
    """A PDF whose page(s) embed a large noise image, oversized enough that the
    pikepdf-lossless attempt alone won't get it under typical test thresholds."""
    image_bytes = make_high_entropy_image_bytes(size=image_size, fmt="PNG")
    doc = fitz.open()
    for _ in range(n_pages):
        page = doc.new_page(width=600, height=600)
        page.insert_image(page.rect, stream=image_bytes)
    data = doc.tobytes()
    doc.close()
    return data
