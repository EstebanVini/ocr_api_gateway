import json
from typing import Any

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential_jitter

from app.config import Settings
from app.core.exceptions import OcrSpaceAuthError, OcrSpaceError, OcrSpaceInvalidResponseError
from app.core.logging import get_logger
from app.models.requests import OcrRequestParams
from app.models.responses import FileParseExitCode, OCRExitCode, OcrResult, Overlay, PageResult

logger = get_logger(__name__)

_AUTH_ERROR_STATUSES = {401, 403}


class _RetryableStatusError(Exception):
    def __init__(self, response: httpx.Response) -> None:
        self.response = response


def _is_retryable(exc: BaseException) -> bool:
    return isinstance(exc, httpx.TimeoutException | httpx.NetworkError | _RetryableStatusError)


def _bool_str(value: bool) -> str:
    return "true" if value else "false"


def _exit_code_name(code: int) -> str:
    try:
        return OCRExitCode(code).name
    except ValueError:
        return "UNKNOWN"


def _page_exit_code_name(code: int) -> str:
    try:
        return FileParseExitCode(code).name
    except ValueError:
        return "UNKNOWN"


def _stringify(value: Any) -> str:
    if isinstance(value, list):
        return " ".join(str(item) for item in value)
    return str(value) if value else ""


class OcrSpaceClient:
    def __init__(self, http_client: httpx.AsyncClient, settings: Settings) -> None:
        self._client = http_client
        self._settings = settings

    async def parse(
        self,
        *,
        file_bytes: bytes,
        filename: str,
        ocr_space_filetype: str,
        mime_type: str,
        params: OcrRequestParams,
    ) -> dict[str, Any]:
        form_data = {
            "language": params.language,
            "filetype": ocr_space_filetype,
            "detectOrientation": _bool_str(params.detect_orientation),
            "isCreateSearchablePdf": _bool_str(params.is_create_searchable_pdf),
            "isSearchablePdfHideTextLayer": _bool_str(False),
            "isOverlayRequired": _bool_str(params.is_overlay_required),
            "OCREngine": str(params.ocr_engine),
            "scale": _bool_str(params.scale),
            "isTable": _bool_str(params.is_table),
        }
        files = {"file": (filename, file_bytes, mime_type)}
        headers = {"apikey": self._settings.ocr_space_api_key}

        response = await self._post_with_retry(form_data, files, headers)
        return self._parse_response(response)

    async def _post_with_retry(
        self,
        data: dict[str, str],
        files: dict[str, tuple[str, bytes, str]],
        headers: dict[str, str],
    ) -> httpx.Response:
        @retry(
            reraise=True,
            stop=stop_after_attempt(self._settings.ocr_max_retries + 1),
            wait=wait_exponential_jitter(initial=1, max=10),
            retry=retry_if_exception(_is_retryable),
        )
        async def _do_request() -> httpx.Response:
            resp = await self._client.post(
                self._settings.ocr_space_endpoint, data=data, files=files, headers=headers
            )
            if resp.status_code >= 500:
                raise _RetryableStatusError(resp)
            return resp

        try:
            return await _do_request()
        except _RetryableStatusError as exc:
            return exc.response

    def _parse_response(self, response: httpx.Response) -> dict[str, Any]:
        if response.status_code in _AUTH_ERROR_STATUSES:
            raise OcrSpaceAuthError(
                "La API key de OCR.space es invalida o se agoto la cuota.",
                details={"status_code": response.status_code},
            )

        try:
            payload: dict[str, Any] = response.json()
        except json.JSONDecodeError as exc:
            raise OcrSpaceInvalidResponseError(
                "OCR.space devolvio una respuesta que no es JSON valido.",
                details={
                    "status_code": response.status_code,
                    "body_preview": response.text[:500],
                },
            ) from exc

        return payload


def map_ocr_space_payload(payload: dict[str, Any], *, include_overlay: bool) -> OcrResult:
    is_errored = bool(payload.get("IsErroredOnProcessing", False))
    exit_code = int(payload.get("OCRExitCode", 4))

    if is_errored or exit_code in (3, 4):
        error_message = _stringify(payload.get("ErrorMessage"))
        error_details = _stringify(payload.get("ErrorDetails"))
        raise OcrSpaceError(
            error_message or "OCR.space no pudo procesar el archivo.",
            details={"error_message": error_message, "error_details": error_details},
        )

    raw_results = payload.get("ParsedResults") or []
    pages: list[PageResult] = []
    searchable_pdf_url: str | None = None

    for i, result in enumerate(raw_results, start=1):
        page_exit_code = int(result.get("FileParseExitCode", -99))
        page_text = (result.get("ParsedText") or "").replace("\r\n", "\n")
        error_message = _stringify(result.get("ErrorMessage")) if page_exit_code != 1 else ""

        overlay: Overlay | None = None
        if include_overlay and result.get("TextOverlay"):
            overlay = Overlay.model_validate(result["TextOverlay"])

        pages.append(
            PageResult(
                page=i,
                exit_code=page_exit_code,
                exit_status=_page_exit_code_name(page_exit_code),
                text=page_text,
                error_message=error_message or None,
                overlay=overlay,
            )
        )

        page_url = result.get("SearchablePDFURL")
        if searchable_pdf_url is None and page_url:
            searchable_pdf_url = page_url

    combined_text = "\n\n".join(p.text for p in pages if p.exit_code == 1)

    return OcrResult(
        exit_code=exit_code,
        exit_status=_exit_code_name(exit_code),
        processing_time_ms=int(payload.get("ProcessingTimeInMilliseconds", 0) or 0),
        text_orientation=str(payload.get("OrientationDetected") or "0"),
        page_count=len(pages),
        text=combined_text,
        pages=pages,
        searchable_pdf_url=searchable_pdf_url,
    )
