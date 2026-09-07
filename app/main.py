from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from asgi_correlation_id import CorrelationIdMiddleware
from fastapi import FastAPI

from app.api.routes.ocr import router as ocr_router
from app.config import get_settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging
from app.services.ocr_client import OcrSpaceClient

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging(settings.log_level)
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(settings.ocr_timeout_seconds),
        limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
    ) as client:
        app.state.ocr_client = OcrSpaceClient(client, settings)
        yield


app = FastAPI(title="OCR API Gateway", version="0.1.0", lifespan=lifespan)
app.add_middleware(CorrelationIdMiddleware)
register_exception_handlers(app)
app.include_router(ocr_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
