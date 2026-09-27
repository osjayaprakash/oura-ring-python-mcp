"""Async client for the Oura API v2 (personal info, daily collections, heart rate)."""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import date, datetime
from typing import Any, TypeVar

import httpx2
from pydantic import TypeAdapter, ValidationError

from oura_ring_mcp.core.endpoints import Collection
from oura_ring_mcp.core.exceptions import (
    AccessDeniedError,
    APIError,
    AuthenticationError,
    MissingScopeError,
    NetworkError,
    RateLimitError,
    ResponseShapeError,
)
from oura_ring_mcp.core.models import HeartRateSample, Page, PersonalInfo
from oura_ring_mcp.core.tokens import StaticToken, TokenSource

BASE_URL = "https://api.ouraring.com"

# Guards against a server that keeps handing out next_token.
MAX_PAGES = 50

_SAMPLES = TypeAdapter(list[HeartRateSample])

# Oura answers a missing scope with 401 and e.g. "Token is not authorized access stress scope."
_MISSING_SCOPE = re.compile(r"not authorized access (\w+) scope")

T = TypeVar("T")


class OuraClient:
    def __init__(
        self,
        auth: str | TokenSource,
        *,
        base_url: str = BASE_URL,
        transport: httpx2.AsyncBaseTransport | None = None,
        timeout: float = 15.0,
    ) -> None:
        self._auth = StaticToken(auth) if isinstance(auth, str) else auth
        self._http = httpx2.AsyncClient(
            base_url=base_url,
            headers={"accept": "application/json"},
            transport=transport,
            timeout=timeout,
        )

    async def __aenter__(self) -> OuraClient:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._http.aclose()

    async def personal_info(self) -> PersonalInfo:
        body = await self._get("/v2/usercollection/personal_info", {}, "personal_info")
        return _parse("personal_info", lambda: PersonalInfo.model_validate(body))

    async def documents(
        self, collection: Collection, start_date: date, end_date: date
    ) -> list[dict[str, Any]]:
        """Every document in [start_date, end_date) as Oura returns it."""
        params = {"start_date": start_date.isoformat(), "end_date": end_date.isoformat()}
        return await self._paged(collection.path, params, collection.value)

    async def heart_rate(self, start: datetime, end: datetime) -> list[HeartRateSample]:
        params = {"start_datetime": start.isoformat(), "end_datetime": end.isoformat()}
        data = await self._paged("/v2/usercollection/heartrate", params, "heartrate")
        return _parse("heartrate", lambda: _SAMPLES.validate_python(data))

    async def _paged(self, path: str, params: dict[str, str], call: str) -> list[dict[str, Any]]:
        documents: list[dict[str, Any]] = []
        next_token: str | None = None
        for _ in range(MAX_PAGES):
            query = params if next_token is None else {**params, "next_token": next_token}
            body = await self._get(path, query, call)
            page = _parse(call, lambda body=body: Page.model_validate(body))
            documents.extend(page.data)
            next_token = page.next_token
            if not next_token:
                return documents
        raise ResponseShapeError(call)

    async def _get(self, path: str, params: dict[str, str], call: str) -> Any:
        response = await self._send(path, params, refresh=False)
        if response.status_code == 401 and (scope := _missing_scope(response)):
            raise MissingScopeError(scope)  # a new token wouldn't help: don't burn a refresh
        if response.status_code == 401 and self._auth.can_refresh:
            # Revoked or expired early: refresh once and retry.
            response = await self._send(path, params, refresh=True)
        if response.status_code == 401:
            raise AuthenticationError("Oura returned HTTP 401")
        if response.status_code == 403:
            raise AccessDeniedError("Oura returned HTTP 403")
        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After", "")
            raise RateLimitError(int(retry_after) if retry_after.isdigit() else None)
        if not response.is_success:
            raise APIError(response.status_code)
        try:
            return response.json()
        except ValueError:
            raise ResponseShapeError(call) from None

    async def _send(self, path: str, params: dict[str, str], *, refresh: bool) -> httpx2.Response:
        token = await self._auth.get(refresh=refresh)
        try:
            return await self._http.get(
                path, params=params, headers={"authorization": f"Bearer {token}"}
            )
        except httpx2.TransportError as exc:
            raise NetworkError(type(exc).__name__) from exc


def _missing_scope(response: httpx2.Response) -> str | None:
    try:
        detail = response.json().get("detail")
    except (ValueError, AttributeError):
        return None
    match = _MISSING_SCOPE.search(detail) if isinstance(detail, str) else None
    return match.group(1) if match else None


def _parse(call: str, build: Callable[[], T]) -> T:
    try:
        return build()
    except (ValidationError, KeyError, TypeError):
        raise ResponseShapeError(call) from None
