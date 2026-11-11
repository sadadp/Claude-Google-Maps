"""Utilidades HTTP con reintentos exponenciales (tenacity) para APIs externas."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, TypeVar

import httpx
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential_jitter,
)

log = logging.getLogger(__name__)

T = TypeVar("T")

RETRYABLE_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}


class ExternalAPIError(RuntimeError):
    """Error no recuperable al hablar con un servicio externo."""

    def __init__(self, service: str, message: str, status: int | None = None) -> None:
        super().__init__(f"[{service}] {message}")
        self.service = service
        self.status = status


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.TransportError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in RETRYABLE_STATUS
    return False


def with_retries(attempts: int = 5) -> Callable[[Callable[..., T]], Callable[..., T]]:
    return retry(
        reraise=True,
        retry=retry_if_exception(_is_retryable),
        stop=stop_after_attempt(attempts),
        wait=wait_exponential_jitter(initial=1, max=30),
        before_sleep=before_sleep_log(log, logging.WARNING),
    )


@with_retries()
def request_json(
    client: httpx.Client,
    method: str,
    url: str,
    *,
    service: str,
    **kwargs: Any,
) -> Any:
    """Hace la petición, reintenta errores transitorios y devuelve el JSON."""
    resp = client.request(method, url, **kwargs)
    if resp.status_code in RETRYABLE_STATUS:
        resp.raise_for_status()  # dispara reintento
    if resp.is_error:
        raise ExternalAPIError(service, f"HTTP {resp.status_code}: {resp.text[:500]}", resp.status_code)
    if not resp.content:
        return {}
    return resp.json()
