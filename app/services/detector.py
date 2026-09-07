from dataclasses import dataclass
from typing import Final

import filetype

from app.core.exceptions import UnsupportedFileTypeError

_OCR_SPACE_TYPES: Final[dict[str, str]] = {
    "pdf": "PDF",
    "gif": "GIF",
    "png": "PNG",
    "jpg": "JPG",
    "jpeg": "JPG",
    "tif": "TIF",
    "tiff": "TIF",
    "bmp": "BMP",
}

_MIME_BY_OCR_SPACE_TYPE: Final[dict[str, str]] = {
    "PDF": "application/pdf",
    "GIF": "image/gif",
    "PNG": "image/png",
    "JPG": "image/jpeg",
    "TIF": "image/tiff",
    "BMP": "image/bmp",
}

_EXTENSION_BY_OCR_SPACE_TYPE: Final[dict[str, str]] = {
    "PDF": "pdf",
    "GIF": "gif",
    "PNG": "png",
    "JPG": "jpg",
    "TIF": "tif",
    "BMP": "bmp",
}


@dataclass(frozen=True)
class DetectedFile:
    ocr_space_filetype: str
    mime_type: str
    extension: str


def detect_file_type(data: bytes) -> DetectedFile:
    """Detecta el tipo real del archivo por sus magic bytes (nunca por nombre/Content-Type).

    Lanza UnsupportedFileTypeError si el contenido no corresponde a ninguno de los
    formatos que acepta OCR.space (PDF, GIF, PNG, JPG, TIF, BMP).
    """
    kind = filetype.guess(data)
    extension = kind.extension.lower() if kind is not None else None
    ocr_space_filetype = _OCR_SPACE_TYPES.get(extension) if extension else None

    if ocr_space_filetype is None:
        detected_mime = kind.mime if kind is not None else "application/octet-stream"
        raise UnsupportedFileTypeError(
            "El tipo de archivo detectado no es soportado por el servicio.",
            details={"detected_mime": detected_mime, "detected_extension": extension},
        )

    return DetectedFile(
        ocr_space_filetype=ocr_space_filetype,
        mime_type=_MIME_BY_OCR_SPACE_TYPE[ocr_space_filetype],
        extension=_EXTENSION_BY_OCR_SPACE_TYPE[ocr_space_filetype],
    )
