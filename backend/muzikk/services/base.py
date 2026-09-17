"""Shared helpers for the external service clients."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = httpx.Timeout(20.0, connect=8.0)


class ServiceError(RuntimeError):
    """Raised when an external service is unreachable or answers an error."""

    def __init__(self, service: str, message: str, status_code: int | None = None) -> None:
        super().__init__(f"{service}: {message}")
        self.service = service
        self.message = message
        self.status_code = status_code


class ServiceNotConfigured(ServiceError):
    def __init__(self, service: str) -> None:
        super().__init__(service, "not configured")


def normalize_base_url(url: str, url_base: str = "") -> str:
    base = (url or "").strip().rstrip("/")
    extra = (url_base or "").strip().strip("/")
    if extra:
        base = f"{base}/{extra}"
    return base


class RateLimiter:
    """Token-less minimum-interval limiter, good enough for one process."""

    def __init__(self, per_second: float) -> None:
        self._interval = 1.0 / per_second if per_second > 0 else 0.0
        self._lock = asyncio.Lock()
        self._next_allowed = 0.0

    async def acquire(self) -> None:
        if self._interval <= 0:
            return
        async with self._lock:
            now = time.monotonic()
            wait = self._next_allowed - now
            if wait > 0:
                await asyncio.sleep(wait)
                now = time.monotonic()
            self._next_allowed = now + self._interval


class HttpService:
    """Small wrapper adding consistent error handling and logging."""

    service_name = "service"

    def __init__(self, base_url: str, headers: dict[str, str] | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.headers = headers or {}

    def _url(self, path: str) -> str:
        if path.startswith("http://") or path.startswith("https://"):
            return path
        return f"{self.base_url}/{path.lstrip('/')}"

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
        data: Any = None,
        content: Any = None,
        headers: dict[str, str] | None = None,
        timeout: httpx.Timeout | float | None = None,
        expect_json: bool = True,
        client: httpx.AsyncClient | None = None,
    ) -> Any:
        # An absolute path carries its own host, so it stays valid even when no
        # base URL is configured: that is how MusicBrainz reaches its fallback.
        absolute = path.startswith(("http://", "https://"))
        if not self.base_url and not absolute:
            raise ServiceNotConfigured(self.service_name)

        merged_headers = {**self.headers, **(headers or {})}
        url = self._url(path)
        owns_client = client is None
        client = client or httpx.AsyncClient(timeout=timeout or DEFAULT_TIMEOUT, follow_redirects=True)
        try:
            response = await client.request(
                method,
                url,
                params=params,
                json=json,
                data=data,
                content=content,
                headers=merged_headers,
                timeout=timeout or DEFAULT_TIMEOUT,
            )
        except httpx.HTTPError as exc:
            raise ServiceError(self.service_name, f"unreachable ({exc.__class__.__name__})") from exc
        finally:
            if owns_client:
                await client.aclose()

        if response.status_code >= 400:
            detail = response.text[:300].replace("\n", " ")
            raise ServiceError(
                self.service_name,
                f"HTTP {response.status_code} on {method} {path} - {detail}",
                response.status_code,
            )

        if not expect_json:
            return response.content
        if not response.content:
            return None
        try:
            return response.json()
        except ValueError as exc:
            raise ServiceError(self.service_name, "invalid JSON response") from exc
