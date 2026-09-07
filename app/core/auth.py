from typing import Annotated

from fastapi import Depends, Header
from starlette.concurrency import run_in_threadpool

from app.config import Settings, get_settings
from app.core.exceptions import InvalidApiKeyError, MissingApiKeyError
from app.services.api_keys import ApiKeyRecord, verify_api_key


async def require_api_key(
    settings: Annotated[Settings, Depends(get_settings)],
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
) -> ApiKeyRecord:
    if not x_api_key:
        raise MissingApiKeyError("Falta el header X-API-Key.", details={})

    record = await run_in_threadpool(verify_api_key, settings.api_keys_db_path, x_api_key)
    if record is None or not record.is_active:
        raise InvalidApiKeyError("La API key no es valida o fue revocada.", details={})

    return record
