"""Where the bearer token comes from: a fixed token, or saved OAuth tokens kept fresh."""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol

from pydantic import ValidationError

from oura_ring_mcp.core.exceptions import AuthorizationError
from oura_ring_mcp.core.oauth import OuraOAuth, TokenSet

# Refresh this long before the access token expires, so it doesn't lapse mid-request.
REFRESH_MARGIN = timedelta(minutes=5)


class TokenSource(Protocol):
    can_refresh: bool

    async def get(self, *, refresh: bool = False) -> str: ...


class StaticToken:
    """A token used as given (a legacy personal access token, or an OAuth access token)."""

    can_refresh = False

    def __init__(self, token: str) -> None:
        self._token = token

    async def get(self, *, refresh: bool = False) -> str:
        return self._token


class TokenStore:
    """OAuth tokens in a JSON file readable only by the owner."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> TokenSet | None:
        try:
            return TokenSet.model_validate_json(self.path.read_text())
        except FileNotFoundError:
            return None
        except (OSError, ValidationError, json.JSONDecodeError):
            raise AuthorizationError("unreadable_token_file") from None

    def save(self, tokens: TokenSet) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        tmp = self.path.with_name(f".{self.path.name}.tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(tokens.model_dump_json())
        os.replace(tmp, self.path)  # atomic: a crash never leaves a half-written file


class OAuthTokens:
    """Saved OAuth tokens, refreshed when near expiry or on demand.

    Oura rotates the refresh token on every refresh, so each new pair is saved at once.
    """

    can_refresh = True

    def __init__(
        self,
        oauth: OuraOAuth,
        store: TokenStore,
        *,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._oauth = oauth
        self._store = store
        self._now = now
        self._lock = asyncio.Lock()
        self._tokens: TokenSet | None = None

    async def get(self, *, refresh: bool = False) -> str:
        async with self._lock:
            if self._tokens is None:
                self._tokens = self._store.load()
            if self._tokens is None:
                raise AuthorizationError("not_signed_in")
            # Another process (e.g. a second MCP client) may have refreshed already.
            on_disk = self._store.load()
            if on_disk is not None and on_disk.expires_at > self._tokens.expires_at:
                self._tokens = on_disk
                refresh = False
            if refresh or self._tokens.expires_at - REFRESH_MARGIN <= self._now():
                self._tokens = await self._oauth.refresh(
                    self._tokens.refresh_token, now=self._now()
                )
                self._store.save(self._tokens)
            return self._tokens.access_token
