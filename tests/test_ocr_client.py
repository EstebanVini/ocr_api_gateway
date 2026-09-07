import asyncio
from typing import Any

import httpx
import pytest
import respx

from app.config import Settings
from app.core.exceptions import OcrSpaceAuthError, OcrSpaceError, OcrSpaceInvalidResponseError
from app.core.logging import configure_logging, get_logger
from app.models.requests import OcrRequestParams
from app.services.ocr_client import OcrSpaceClient, map_ocr_space_payload

_ENDPOINT = "https://api.ocr.space/parse/image"


async def _instant_sleep(_seconds: float) -> None:
    """Replaces asyncio.sleep in retry tests so backoff delays don't slow down the suite."""
    return None


def _make_client(**overrides: object) -> tuple[Settings, OcrSpaceClient]:
    settings = Settings(OCR_SPACE_API_KEY="test-key", **overrides)  # type: ignore[arg-type]
    http_client = httpx.AsyncClient()
    return settings, OcrSpaceClient(http_client, settings)


def _success_payload(text: str = "hola\r\nmundo") -> dict[str, Any]:
    return {
        "IsErroredOnProcessing": False,
        "OCRExitCode": 1,
        "ProcessingTimeInMilliseconds": "1500",
        "ParsedResults": [
            {
                "FileParseExitCode": 1,
                "ParsedText": text,
                "ErrorMessage": "",
            }
        ],
    }


async def _parse(client: OcrSpaceClient) -> dict[str, Any]:
    return await client.parse(
        file_bytes=b"fake-bytes",
        filename="upload.jpg",
        ocr_space_filetype="JPG",
        mime_type="image/jpeg",
        params=OcrRequestParams(),
    )


@respx.mock
async def test_success_maps_to_normalized_result() -> None:
    respx.post(_ENDPOINT).mock(return_value=httpx.Response(200, json=_success_payload()))
    _, client = _make_client()

    payload = await _parse(client)
    result = map_ocr_space_payload(payload, include_overlay=False)

    assert result.exit_status == "SUCCESS"
    assert result.pages[0].text == "hola\nmundo"  # \r\n normalized to \n
    assert result.text == "hola\nmundo"


@respx.mock
async def test_partial_success_marks_failed_page_without_raising() -> None:
    payload = {
        "IsErroredOnProcessing": False,
        "OCRExitCode": 2,
        "ProcessingTimeInMilliseconds": "800",
        "ParsedResults": [
            {"FileParseExitCode": 1, "ParsedText": "pagina ok", "ErrorMessage": ""},
            {"FileParseExitCode": -10, "ParsedText": "", "ErrorMessage": "engine error"},
        ],
    }
    respx.post(_ENDPOINT).mock(return_value=httpx.Response(200, json=payload))
    _, client = _make_client()

    raw = await _parse(client)
    result = map_ocr_space_payload(raw, include_overlay=False)

    assert result.exit_status == "PARTIAL_SUCCESS"
    assert result.pages[1].error_message == "engine error"
    assert result.text == "pagina ok"  # failed page excluded from concatenation


@pytest.mark.parametrize("exit_code", [3, 4])
@respx.mock
async def test_fatal_or_parse_failed_raises_with_ocr_space_message(exit_code: int) -> None:
    payload = {
        "IsErroredOnProcessing": True,
        "OCRExitCode": exit_code,
        "ErrorMessage": ["Something broke"],
        "ErrorDetails": "boom",
        "ParsedResults": [],
    }
    respx.post(_ENDPOINT).mock(return_value=httpx.Response(200, json=payload))
    _, client = _make_client()

    raw = await _parse(client)
    with pytest.raises(OcrSpaceError) as exc_info:
        map_ocr_space_payload(raw, include_overlay=False)

    assert exc_info.value.http_status == 502
    assert "Something broke" in exc_info.value.details["error_message"]


@respx.mock
async def test_malformed_non_json_body_raises_invalid_response() -> None:
    respx.post(_ENDPOINT).mock(
        return_value=httpx.Response(200, text="Rate limit exceeded, try later")
    )
    _, client = _make_client()

    with pytest.raises(OcrSpaceInvalidResponseError) as exc_info:
        await _parse(client)

    assert "Rate limit exceeded" in exc_info.value.details["body_preview"]


@pytest.mark.parametrize("status_code", [401, 403])
@respx.mock
async def test_auth_error_raises_without_retrying(status_code: int) -> None:
    route = respx.post(_ENDPOINT).mock(return_value=httpx.Response(status_code, text="Forbidden"))
    _, client = _make_client(OCR_MAX_RETRIES=2)

    with pytest.raises(OcrSpaceAuthError):
        await _parse(client)

    assert route.call_count == 1  # 4xx must never trigger a retry


@respx.mock
async def test_retries_on_5xx_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(asyncio, "sleep", _instant_sleep)
    route = respx.post(_ENDPOINT).mock(
        side_effect=[
            httpx.Response(503, text="temporarily down"),
            httpx.Response(200, json=_success_payload()),
        ]
    )
    _, client = _make_client(OCR_MAX_RETRIES=2)

    payload = await _parse(client)

    assert route.call_count == 2
    assert payload["OCRExitCode"] == 1


@respx.mock
async def test_retries_exhausted_on_persistent_5xx(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(asyncio, "sleep", _instant_sleep)
    route = respx.post(_ENDPOINT).mock(return_value=httpx.Response(503, text="down"))
    _, client = _make_client(OCR_MAX_RETRIES=2)

    # after exhausting retries, the last (still-failing) response flows through and
    # its non-JSON body surfaces as a clear error instead of a silent empty success
    with pytest.raises(OcrSpaceInvalidResponseError):
        await _parse(client)

    assert route.call_count == 3  # 1 initial attempt + 2 retries, then gives up


@respx.mock
async def test_request_shape_sends_all_required_fields() -> None:
    route = respx.post(_ENDPOINT).mock(return_value=httpx.Response(200, json=_success_payload()))
    _, client = _make_client()

    await _parse(client)

    request = route.calls.last.request
    assert request.headers["apikey"] == "test-key"
    body = request.content.decode("latin-1")
    for field in (
        "language",
        "filetype",
        "detectOrientation",
        "isCreateSearchablePdf",
        "isSearchablePdfHideTextLayer",
        "isOverlayRequired",
        "OCREngine",
        "scale",
        "isTable",
    ):
        assert f'name="{field}"' in body
    assert "true" in body or "false" in body
    assert 'name="file"' in body
    assert "upload.jpg" in body


@respx.mock
async def test_api_key_never_appears_in_logs(capsys: pytest.CaptureFixture[str]) -> None:
    respx.post(_ENDPOINT).mock(return_value=httpx.Response(403, text="Forbidden"))
    settings, client = _make_client()
    configure_logging("INFO")
    logger = get_logger(__name__)

    try:
        await _parse(client)
    except OcrSpaceAuthError:
        logger.warning("ocr_auth_failed", api_key=settings.ocr_space_api_key)

    captured = capsys.readouterr()
    assert settings.ocr_space_api_key not in captured.out
    assert settings.ocr_space_api_key not in captured.err
