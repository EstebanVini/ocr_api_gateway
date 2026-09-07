import fitz
import pytest

from app.core.exceptions import (
    CompressionFailedError,
    CorruptOrEncryptedFileError,
    PdfPageLimitExceededError,
)
from app.services.compressor.base import CompressionStrategy
from app.services.compressor.pdf import compress_pdf, validate_page_count
from tests.conftest import (
    make_corrupt_pdf_bytes,
    make_pdf_bytes,
    make_pdf_with_large_embedded_image_bytes,
)


def test_validate_page_count_within_limit_returns_count() -> None:
    data = make_pdf_bytes(n_pages=2)
    assert validate_page_count(data, max_pages=3) == 2


def test_validate_page_count_exceeds_limit_raises_exact_message() -> None:
    data = make_pdf_bytes(n_pages=4)

    with pytest.raises(PdfPageLimitExceededError) as exc_info:
        validate_page_count(data, max_pages=3)

    exc = exc_info.value
    assert exc.http_status == 422
    assert exc.message == ("El plan actual de OCR.space acepta máximo 3 páginas; el PDF tiene 4")
    assert exc.details == {"page_count": 4, "max_pages": 3}


def test_corrupt_pdf_raises_corrupt_or_encrypted_on_page_validation() -> None:
    with pytest.raises(CorruptOrEncryptedFileError):
        validate_page_count(make_corrupt_pdf_bytes(), max_pages=3)


def test_corrupt_pdf_raises_corrupt_or_encrypted_on_compression() -> None:
    with pytest.raises(CorruptOrEncryptedFileError):
        compress_pdf(make_corrupt_pdf_bytes(), max_bytes=1_000, min_dpi=150)


def test_passthrough_when_already_under_threshold() -> None:
    data = make_pdf_bytes(n_pages=1)
    result = compress_pdf(data, max_bytes=1_048_576, min_dpi=150)
    assert result.was_compressed is False
    assert result.strategy == CompressionStrategy.NONE
    assert result.data == data


def test_pikepdf_lossless_success_stops_the_cascade(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.services.compressor.pdf as pdf_mod

    data = make_pdf_with_large_embedded_image_bytes(image_size=(1600, 1600))

    def _fail_if_called(*args: object, **kwargs: object) -> bytes:
        raise AssertionError("later cascade stage should not run when pikepdf already fit")

    monkeypatch.setattr(pdf_mod, "_pymupdf_rewrite", _fail_if_called)
    monkeypatch.setattr(pdf_mod, "_rasterize_to_pdf", _fail_if_called)

    result = compress_pdf(data, max_bytes=3_700_000, min_dpi=150)

    assert result.strategy == CompressionStrategy.PIKEPDF_LOSSLESS
    assert len(result.data) <= 3_700_000


def test_falls_through_to_pymupdf_rewrite_when_pikepdf_not_enough() -> None:
    data = make_pdf_with_large_embedded_image_bytes(image_size=(1600, 1600))

    result = compress_pdf(data, max_bytes=1_200_000, min_dpi=150)

    assert result.strategy == CompressionStrategy.PYMUPDF_REWRITE
    assert len(result.data) <= 1_200_000


def test_falls_through_to_rasterize_cascade_and_respects_min_dpi() -> None:
    data = make_pdf_with_large_embedded_image_bytes(image_size=(1600, 1600))

    result = compress_pdf(data, max_bytes=1_000_000, min_dpi=150)

    assert result.strategy == CompressionStrategy.PDF_RASTERIZE
    assert result.dpi == 150
    assert len(result.data) <= 1_000_000

    out = fitz.open(stream=result.data, filetype="pdf")
    try:
        assert out.page_count == 1
    finally:
        out.close()


def test_dpi_floor_exhaustion_raises_with_full_detail() -> None:
    data = make_pdf_with_large_embedded_image_bytes(image_size=(1600, 1600))

    with pytest.raises(CompressionFailedError) as exc_info:
        compress_pdf(data, max_bytes=500_000, min_dpi=150)

    details = exc_info.value.details
    assert details["original_size_bytes"] == len(data)
    assert details["final_size_bytes"] > 0
    assert details["strategy"] == CompressionStrategy.PDF_RASTERIZE.value
    assert details["last_parameter_tried"] == {"dpi": 150}
