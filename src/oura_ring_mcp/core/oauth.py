"""Oura OAuth2 authorization-code flow: authorize URL, code exchange and token refresh."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import httpx2
from pydantic import BaseModel, ValidationError

from oura_ring_mcp.core.exceptions import (
    APIError,
    AuthorizationError,
    NetworkError,
    RateLimitError,
    ResponseShapeError,
)

AUTHORIZE_URL = "https://cloud.ouraring.com/oauth/authorize"
TOKEN_URL = "https://api.ouraring.com/oauth/token"

# Everything the tools read. Stress and resilience come under `daily`.
DEFAULT_SCOPES = ("email", "personal", "daily", "heartrate", "workout", "session", "spo2")


class TokenSet(BaseModel):
    access_token: str
    refresh_token: str
    expires_at: datetime  # UTC

    def __repr__(self) -> str:
        return f"TokenSet(expires_at={self.expires_at.isoformat()})"

    __str__ = __repr__


class OuraOAuth:
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        *,
        scopes: tuple[str, ...] = DEFAULT_SCOPES,
        transport: httpx2.AsyncBaseTransport | None = None,
        timeout: float = 15.0,
    ) -> None:
        self.redirect_uri = redirect_uri
        self._client_id = client_id
        self._client_secret = client_secret
        self._scopes = scopes
        self._transport = transport
        self._timeout = timeout

    def authorize_url(self, state: str) -> str:
        query = {
            "response_type": "code",
            "client_id": self._client_id,
            "redirect_uri": self.redirect_uri,
            "scope": " ".join(self._scopes),
            "state": state,
        }
        return f"{AUTHORIZE_URL}?{urlencode(query)}"

    async def exchange_code(self, code: str, *, now: datetime | None = None) -> TokenSet:
        form = {"grant_type": "authorization_code", "code": code, "redirect_uri": self.redirect_uri}
        return await self._token_request(form, "exchange_code", now=now)

    async def refresh(self, refresh_token: str, *, now: datetime | None = None) -> TokenSet:
        form = {"grant_type": "refresh_token", "refresh_token": refresh_token}
        return await self._token_request(
            form, "refresh", now=now, previous_refresh_token=refresh_token
        )

    async def _token_request(
        self,
        form: dict[str, str],
        call: str,
        *,
        now: datetime | None,
        previous_refresh_token: str | None = None,
    ) -> TokenSet:
        form = {**form, "client_id": self._client_id, "client_secret": self._client_secret}
        try:
            async with httpx2.AsyncClient(transport=self._transport, timeout=self._timeout) as http:
                response = await http.post(TOKEN_URL, data=form)
        except httpx2.TransportError as exc:
            raise NetworkError(type(exc).__name__) from exc
        if response.status_code in (400, 401):
            # invalid_grant (code or refresh token used, expired or revoked) or bad client.
            raise AuthorizationError(_oauth_error(response))
        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After", "")
            raise RateLimitError(int(retry_after) if retry_after.isdigit() else None)
        if not response.is_success:
            raise APIError(response.status_code)
        try:
            body = response.json()
            refresh_token = body.get("refresh_token") or previous_refresh_token
            return TokenSet(
                access_token=body["access_token"],
                refresh_token=refresh_token,
                expires_at=(now or datetime.now(UTC)) + timedelta(seconds=body["expires_in"]),
            )
        except (ValueError, KeyError, TypeError, AttributeError, ValidationError):
            raise ResponseShapeError(call) from None


def _oauth_error(response: httpx2.Response) -> str:
    """The OAuth `error` code, e.g. invalid_grant; never the description, which may echo input."""
    try:
        body: Any = response.json()
    except ValueError:
        body = None
    error = body.get("error") if isinstance(body, dict) else None
    if isinstance(error, str) and error.isidentifier():
        return error
    return f"HTTP {response.status_code}"
