import time
from asyncio import Lock
from collections import defaultdict, deque
from typing import Annotated

from fastapi import Depends, Request

from app.core.auth import require_api_key
from app.core.exceptions import RateLimitExceededError
from app.services.api_keys import ApiKeyRecord


class SlidingWindowRateLimiter:
    """Limitador de tasa en memoria, con ventana deslizante, por proceso.

    Corriendo con varios workers de uvicorn cada proceso lleva su propio conteo
    (no hay estado compartido entre procesos), asi que el techo global efectivo
    es aproximadamente `workers * max_requests` peticiones por ventana. Para el
    volumen de este gateway no justifica un backend externo (ej. Redis); si se
    necesita un limite global exacto entre procesos, correr con un solo worker.
    """

    def __init__(self, max_requests: int, window_seconds: float) -> None:
        self._max_requests = max_requests
        self._window_seconds = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    async def check(self, key: str) -> tuple[bool, int]:
        """Devuelve (permitido, segundos_para_reintentar)."""
        now = time.monotonic()
        async with self._lock:
            hits = self._hits[key]
            cutoff = now - self._window_seconds
            while hits and hits[0] < cutoff:
                hits.popleft()

            if len(hits) >= self._max_requests:
                retry_after = max(1, int(hits[0] + self._window_seconds - now) + 1)
                return False, retry_after

            hits.append(now)
            return True, 0


async def enforce_rate_limit(
    request: Request,
    api_key: Annotated[ApiKeyRecord, Depends(require_api_key)],
) -> None:
    limiter: SlidingWindowRateLimiter = request.app.state.rate_limiter
    allowed, retry_after = await limiter.check(f"api_key:{api_key.id}")
    if not allowed:
        raise RateLimitExceededError(
            "Se supero el limite de peticiones permitidas. Intenta de nuevo mas tarde.",
            details={"retry_after_seconds": retry_after},
            headers={"Retry-After": str(retry_after)},
        )
