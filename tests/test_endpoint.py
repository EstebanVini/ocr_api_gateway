from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
import respx
from httpx import ASGITransport

from app.config import Settings, get_settings
from app.core.exceptions import CompressionFailedError
from app.main import app
from tests.conftest import make_image_bytes, make_low_entropy_png_bytes, make_pdf_bytes
from tests.test_passport_mrz import _MATCHING_TEXT

_ENDPOINT = "https://api.ocr.space/parse/image"


def _success_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "IsErroredOnProcessing": False,
        "OCRExitCode": 1,
        "ProcessingTimeInMilliseconds": "1200",
        "ParsedResults": [
            {"FileParseExitCode": 1, "ParsedText": "hello world", "ErrorMessage": ""}
        ],
    }
    payload.update(overrides)
    return payload


@pytest.fixture
async def client(test_api_key: str) -> AsyncIterator[httpx.AsyncClient]:
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test", headers={"X-API-Key": test_api_key}
        ) as ac:
            yield ac
    app.dependency_overrides.clear()


async def test_health_endpoint() -> None:
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


async def test_limits_endpoint_matches_settings(client: httpx.AsyncClient) -> None:
    resp = await client.get("/api/v1/ocr/limits")
    assert resp.status_code == 200
    settings = get_settings()
    assert resp.json() == {
        "max_upload_bytes": settings.ocr_max_upload_bytes,
        "max_pdf_pages": settings.ocr_max_pdf_pages,
        "max_input_bytes": settings.ocr_max_input_bytes,
        "min_jpeg_quality": settings.ocr_min_jpeg_quality,
        "min_pdf_dpi": settings.ocr_min_pdf_dpi,
        "timeout_seconds": settings.ocr_timeout_seconds,
    }


async def test_openapi_schema_is_well_formed(client: httpx.AsyncClient) -> None:
    resp = await client.get("/openapi.json")
    assert resp.status_code == 200
    schema = resp.json()
    assert "/api/v1/ocr" in schema["paths"]
    assert "/api/v1/ocr/limits" in schema["paths"]


@respx.mock
async def test_happy_path_returns_normalized_response(client: httpx.AsyncClient) -> None:
    respx.post(_ENDPOINT).mock(return_value=httpx.Response(200, json=_success_payload()))

    files = {"file": ("photo.jpg", make_image_bytes("JPEG", size=(20, 20)), "image/jpeg")}
    resp = await client.post("/api/v1/ocr", files=files)

    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["file"]["was_compressed"] is False
    assert body["file"]["detected_type"] == "JPG"
    assert body["ocr"]["exit_status"] == "SUCCESS"
    assert body["ocr"]["text"] == "hello world"
    assert body["raw"] is None


@respx.mock
async def test_ocr_engine_sent_as_form_string_is_accepted(client: httpx.AsyncClient) -> None:
    # multipart/form-data always sends scalar values as strings ("2", not 2) — this is the
    # real-world shape every client sends, and is what regressed to a 422 before the fix.
    respx.post(_ENDPOINT).mock(return_value=httpx.Response(200, json=_success_payload()))

    files = {"file": ("photo.jpg", make_image_bytes("JPEG", size=(20, 20)), "image/jpeg")}
    resp = await client.post("/api/v1/ocr", files=files, data={"ocr_engine": "2"})

    assert resp.status_code == 200
    assert resp.json()["request"]["ocr_engine"] == 2


async def test_out_of_range_ocr_engine_returns_422_not_500(client: httpx.AsyncClient) -> None:
    files = {"file": ("photo.jpg", make_image_bytes("JPEG", size=(20, 20)), "image/jpeg")}
    resp = await client.post("/api/v1/ocr", files=files, data={"ocr_engine": "99"})

    assert resp.status_code == 422
    body = resp.json()
    assert body["success"] is False
    assert body["error"]["code"] == "VALIDATION_ERROR"


@respx.mock
async def test_oversized_image_gets_compressed_before_sending(client: httpx.AsyncClient) -> None:
    respx.post(_ENDPOINT).mock(return_value=httpx.Response(200, json=_success_payload()))
    data = make_low_entropy_png_bytes(size=(1200, 1200))
    assert len(data) > 1_048_576

    files = {"file": ("scan.png", data, "image/png")}
    resp = await client.post("/api/v1/ocr", files=files)

    assert resp.status_code == 200
    body = resp.json()
    assert body["file"]["was_compressed"] is True
    assert body["file"]["sent_size_bytes"] <= 1_048_576
    assert body["file"]["compression"]["strategy"] == "png_optimize"


async def test_unsupported_file_type_returns_415(client: httpx.AsyncClient) -> None:
    files = {"file": ("notes.txt", b"just plain text bytes", "text/plain")}
    resp = await client.post("/api/v1/ocr", files=files)

    assert resp.status_code == 415
    body = resp.json()
    assert body["success"] is False
    assert body["error"]["code"] == "UNSUPPORTED_FILE_TYPE"
    assert "detected_mime" in body["error"]["details"]


async def test_pdf_over_page_limit_returns_422_with_exact_message(
    client: httpx.AsyncClient,
) -> None:
    data = make_pdf_bytes(n_pages=4)
    files = {"file": ("doc.pdf", data, "application/pdf")}
    resp = await client.post("/api/v1/ocr", files=files)

    assert resp.status_code == 422
    body = resp.json()
    assert body["error"]["code"] == "PDF_PAGE_LIMIT_EXCEEDED"
    assert body["error"]["message"] == (
        "El plan actual de OCR.space acepta máximo 3 páginas; el PDF tiene 4"
    )


async def test_compression_exhaustion_returns_413(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.api.routes.ocr as ocr_route

    def _always_fails(*_args: object, **_kwargs: object) -> None:
        raise CompressionFailedError(
            "No se pudo comprimir",
            details={
                "original_size_bytes": 999,
                "final_size_bytes": 999,
                "strategy": "jpeg_quality_search_scaled",
                "last_parameter_tried": {"quality": 60, "scale_factor": 0.5},
            },
        )

    monkeypatch.setattr(ocr_route, "compress_if_needed", _always_fails)

    files = {"file": ("photo.jpg", make_image_bytes("JPEG", size=(20, 20)), "image/jpeg")}
    resp = await client.post("/api/v1/ocr", files=files)

    assert resp.status_code == 413
    assert resp.json()["error"]["code"] == "COMPRESSION_FAILED"


@respx.mock
async def test_ocr_space_fatal_error_returns_502(client: httpx.AsyncClient) -> None:
    respx.post(_ENDPOINT).mock(
        return_value=httpx.Response(
            200,
            json={
                "IsErroredOnProcessing": True,
                "OCRExitCode": 4,
                "ErrorMessage": "Invalid API key",
                "ErrorDetails": "quota exceeded",
                "ParsedResults": [],
            },
        )
    )
    files = {"file": ("photo.jpg", make_image_bytes("JPEG", size=(20, 20)), "image/jpeg")}
    resp = await client.post("/api/v1/ocr", files=files)

    assert resp.status_code == 502
    body = resp.json()
    assert body["error"]["code"] == "OCR_SPACE_ERROR"
    assert "Invalid API key" in body["error"]["details"]["error_message"]


async def test_raw_input_too_large_returns_413(client: httpx.AsyncClient) -> None:
    tiny_settings = Settings(OCR_SPACE_API_KEY="test-key", OCR_MAX_INPUT_BYTES=10)
    app.dependency_overrides[get_settings] = lambda: tiny_settings

    files = {"file": ("photo.jpg", make_image_bytes("JPEG", size=(20, 20)), "image/jpeg")}
    resp = await client.post("/api/v1/ocr", files=files)

    assert resp.status_code == 413
    assert resp.json()["error"]["code"] == "FILE_TOO_LARGE"


def test_missing_api_key_fails_settings_construction(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OCR_SPACE_API_KEY", raising=False)
    with pytest.raises(Exception):  # noqa: B017 - pydantic ValidationError
        Settings(_env_file=None)  # type: ignore[call-arg]


async def test_request_without_api_key_header_returns_401() -> None:
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get("/api/v1/ocr/limits")

    assert resp.status_code == 401
    body = resp.json()
    assert body["success"] is False
    assert body["error"]["code"] == "MISSING_API_KEY"


async def test_request_with_invalid_api_key_returns_401() -> None:
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test", headers={"X-API-Key": "not-a-real-key"}
        ) as ac:
            resp = await ac.get("/api/v1/ocr/limits")

    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "INVALID_API_KEY"


async def test_request_with_revoked_api_key_returns_401(_api_keys_db_path: str) -> None:
    from app.services.api_keys import create_api_key, revoke_api_key

    key_id, raw_key = create_api_key(_api_keys_db_path, "revoked-key-test")
    revoke_api_key(_api_keys_db_path, key_id)

    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test", headers={"X-API-Key": raw_key}
        ) as ac:
            resp = await ac.get("/api/v1/ocr/limits")

    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "INVALID_API_KEY"


async def test_health_endpoint_does_not_require_api_key() -> None:
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get("/health")

    assert resp.status_code == 200


async def test_rate_limit_exceeded_returns_429(test_api_key: str) -> None:
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setenv("RATE_LIMIT_REQUESTS", "1")
    monkeypatch.setenv("RATE_LIMIT_WINDOW_SECONDS", "60")
    get_settings.cache_clear()

    try:
        async with app.router.lifespan_context(app):
            transport = ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://test", headers={"X-API-Key": test_api_key}
            ) as ac:
                resp_first = await ac.get("/api/v1/ocr/limits")
                resp_second = await ac.get("/api/v1/ocr/limits")
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()

    assert resp_first.status_code == 200
    assert resp_second.status_code == 429
    body = resp_second.json()
    assert body["error"]["code"] == "RATE_LIMIT_EXCEEDED"
    assert "Retry-After" in resp_second.headers


@respx.mock
async def test_include_raw_toggles_raw_field(client: httpx.AsyncClient) -> None:
    respx.post(_ENDPOINT).mock(return_value=httpx.Response(200, json=_success_payload()))
    file_bytes = make_image_bytes("JPEG", size=(20, 20))

    resp_without = await client.post(
        "/api/v1/ocr", files={"file": ("photo.jpg", file_bytes, "image/jpeg")}
    )
    assert resp_without.json()["raw"] is None

    resp_with = await client.post(
        "/api/v1/ocr",
        files={"file": ("photo.jpg", file_bytes, "image/jpeg")},
        data={"include_raw": "true"},
    )
    assert resp_with.json()["raw"] is not None
    assert resp_with.json()["raw"]["OCRExitCode"] == 1


@respx.mock
async def test_overlay_forced_null_when_not_requested(client: httpx.AsyncClient) -> None:
    payload = _success_payload(
        ParsedResults=[
            {
                "FileParseExitCode": 1,
                "ParsedText": "hello",
                "ErrorMessage": "",
                "TextOverlay": {"Lines": [], "HasOverlay": True},
            }
        ]
    )
    respx.post(_ENDPOINT).mock(return_value=httpx.Response(200, json=payload))

    files = {"file": ("photo.jpg", make_image_bytes("JPEG", size=(20, 20)), "image/jpeg")}
    resp = await client.post("/api/v1/ocr", files=files, data={"is_overlay_required": "false"})

    assert resp.status_code == 200
    assert resp.json()["ocr"]["pages"][0]["overlay"] is None


@respx.mock
async def test_passport_field_is_null_for_non_passport_document(
    client: httpx.AsyncClient,
) -> None:
    respx.post(_ENDPOINT).mock(return_value=httpx.Response(200, json=_success_payload()))

    files = {"file": ("invoice.jpg", make_image_bytes("JPEG", size=(20, 20)), "image/jpeg")}
    resp = await client.post("/api/v1/ocr", files=files)

    assert resp.status_code == 200
    assert resp.json()["passport"] is None


@respx.mock
async def test_passport_detected_and_matches_visible_text(client: httpx.AsyncClient) -> None:
    respx.post(_ENDPOINT).mock(
        return_value=httpx.Response(
            200,
            json=_success_payload(
                ParsedResults=[
                    {"FileParseExitCode": 1, "ParsedText": _MATCHING_TEXT, "ErrorMessage": ""}
                ]
            ),
        )
    )

    files = {"file": ("passport.jpg", make_image_bytes("JPEG", size=(20, 20)), "image/jpeg")}
    resp = await client.post("/api/v1/ocr", files=files)

    assert resp.status_code == 200
    passport = resp.json()["passport"]
    assert passport is not None
    assert passport["mrz"]["passport_number"] == "XDF235217"
    assert passport["mrz"]["surname"] == "VINIEGRA PEREZ OLAGARAY"
    assert passport["mrz"]["checksum_valid"] is True
    assert passport["matches_visible_text"] is True
    assert passport["validation_error"] is None


@respx.mock
async def test_passport_mismatch_reports_custom_validation_error(
    client: httpx.AsyncClient,
) -> None:
    tampered_text = _MATCHING_TEXT.replace("XDF235217", "ZZZ999999", 1)
    respx.post(_ENDPOINT).mock(
        return_value=httpx.Response(
            200,
            json=_success_payload(
                ParsedResults=[
                    {"FileParseExitCode": 1, "ParsedText": tampered_text, "ErrorMessage": ""}
                ]
            ),
        )
    )

    files = {"file": ("passport.jpg", make_image_bytes("JPEG", size=(20, 20)), "image/jpeg")}
    resp = await client.post("/api/v1/ocr", files=files)

    assert resp.status_code == 200  # a mismatch is reported inline, not a request failure
    passport = resp.json()["passport"]
    assert passport is not None
    assert passport["matches_visible_text"] is False
    assert "no coinciden" in passport["validation_error"]
