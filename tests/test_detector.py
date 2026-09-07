import pytest

from app.core.exceptions import UnsupportedFileTypeError
from app.services.detector import detect_file_type
from tests.conftest import make_image_bytes, make_pdf_bytes


@pytest.mark.parametrize(
    ("fmt", "expected_type", "expected_mime", "expected_ext"),
    [
        ("PNG", "PNG", "image/png", "png"),
        ("JPEG", "JPG", "image/jpeg", "jpg"),
        ("GIF", "GIF", "image/gif", "gif"),
        ("BMP", "BMP", "image/bmp", "bmp"),
        ("TIFF", "TIF", "image/tiff", "tif"),
    ],
)
def test_detects_each_image_format(
    fmt: str, expected_type: str, expected_mime: str, expected_ext: str
) -> None:
    data = make_image_bytes(fmt)
    detected = detect_file_type(data)
    assert detected.ocr_space_filetype == expected_type
    assert detected.mime_type == expected_mime
    assert detected.extension == expected_ext


def test_detects_pdf() -> None:
    detected = detect_file_type(make_pdf_bytes())
    assert detected.ocr_space_filetype == "PDF"
    assert detected.mime_type == "application/pdf"
    assert detected.extension == "pdf"


def test_ignores_filename_and_relies_only_on_magic_bytes() -> None:
    # A JPEG whose bytes never mention a filename/content-type must still be detected as JPG,
    # proving detection never looks at anything other than the byte content itself.
    data = make_image_bytes("JPEG")
    detected = detect_file_type(data)
    assert detected.ocr_space_filetype == "JPG"


def test_unsupported_type_raises_with_detected_mime_in_details() -> None:
    with pytest.raises(UnsupportedFileTypeError) as exc_info:
        detect_file_type(b"this is not a real file, just plain text bytes")

    exc = exc_info.value
    assert exc.http_status == 415
    assert "detected_mime" in exc.details


def test_empty_bytes_raise_unsupported_file_type() -> None:
    with pytest.raises(UnsupportedFileTypeError):
        detect_file_type(b"")
