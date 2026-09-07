from typing import Annotated

from fastapi import APIRouter, Depends, Request, UploadFile
from starlette.concurrency import run_in_threadpool

from app.config import Settings, get_settings
from app.core.exceptions import RawInputTooLargeError
from app.core.rate_limit import enforce_rate_limit
from app.models.requests import OcrRequestParams
from app.models.responses import CompressionInfo, FileInfo, LimitsResponse, OcrResponse, RequestEcho
from app.services.compressor.base import compress_if_needed
from app.services.compressor.pdf import validate_page_count
from app.services.detector import detect_file_type
from app.services.ocr_client import OcrSpaceClient, map_ocr_space_payload
from app.services.passport_mrz import detect_passport

router = APIRouter(prefix="/api/v1", tags=["ocr"], dependencies=[Depends(enforce_rate_limit)])

_UPLOAD_READ_CHUNK_SIZE = 1024 * 1024


def get_ocr_client(request: Request) -> OcrSpaceClient:
    return request.app.state.ocr_client  # type: ignore[no-any-return]


async def _read_upload_capped(file: UploadFile, max_bytes: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(_UPLOAD_READ_CHUNK_SIZE)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise RawInputTooLargeError(
                f"El archivo subido supera el limite de {max_bytes} bytes.",
                details={"max_input_bytes": max_bytes},
            )
        chunks.append(chunk)
    return b"".join(chunks)


@router.get("/ocr/limits", response_model=LimitsResponse)
async def get_limits(settings: Annotated[Settings, Depends(get_settings)]) -> LimitsResponse:
    return LimitsResponse(
        max_upload_bytes=settings.ocr_max_upload_bytes,
        max_pdf_pages=settings.ocr_max_pdf_pages,
        max_input_bytes=settings.ocr_max_input_bytes,
        min_jpeg_quality=settings.ocr_min_jpeg_quality,
        min_pdf_dpi=settings.ocr_min_pdf_dpi,
        timeout_seconds=settings.ocr_timeout_seconds,
    )


@router.post("/ocr", response_model=OcrResponse)
async def create_ocr(
    file: UploadFile,
    params: Annotated[OcrRequestParams, Depends(OcrRequestParams.as_form)],
    settings: Annotated[Settings, Depends(get_settings)],
    ocr_client: Annotated[OcrSpaceClient, Depends(get_ocr_client)],
) -> OcrResponse:
    raw = await _read_upload_capped(file, settings.ocr_max_input_bytes)
    detected = detect_file_type(raw)

    if detected.ocr_space_filetype == "PDF":
        await run_in_threadpool(validate_page_count, raw, settings.ocr_max_pdf_pages)

    # La compresion (busqueda de calidad JPEG, rasterizado de PDF, etc.) es CPU-bound
    # y puede tomar cientos de ms a varios segundos: se corre en el threadpool para no
    # bloquear el event loop y permitir que otras peticiones avancen en paralelo.
    result = await run_in_threadpool(compress_if_needed, raw, detected.ocr_space_filetype, settings)
    final = detect_file_type(result.data) if result.was_compressed else detected

    raw_payload = await ocr_client.parse(
        file_bytes=result.data,
        filename=f"upload.{final.extension}",
        ocr_space_filetype=final.ocr_space_filetype,
        mime_type=final.mime_type,
        params=params,
    )
    ocr_result = map_ocr_space_payload(raw_payload, include_overlay=params.is_overlay_required)
    passport = detect_passport(ocr_result.text)

    return OcrResponse(
        file=FileInfo(
            filename=file.filename or "upload",
            detected_type=final.ocr_space_filetype,
            mime_type=final.mime_type,
            original_size_bytes=len(raw),
            sent_size_bytes=len(result.data),
            was_compressed=result.was_compressed,
            compression=CompressionInfo(
                strategy=result.strategy.value,
                quality=result.quality,
                scale_factor=result.scale_factor,
                dpi=result.dpi,
                elapsed_ms=result.elapsed_ms,
            )
            if result.was_compressed
            else None,
        ),
        request=RequestEcho(
            language=params.language,
            ocr_engine=params.ocr_engine,
            detect_orientation=params.detect_orientation,
            searchable_pdf=params.is_create_searchable_pdf,
        ),
        ocr=ocr_result,
        passport=passport,
        raw=raw_payload if params.include_raw else None,
    )
