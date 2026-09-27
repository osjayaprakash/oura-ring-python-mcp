"""Where the bearer token comes from: a fixed token, or saved OAuth tokens kept fresh."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import tempfile
import time
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol

from pydantic import ValidationError

from oura_ring_mcp.core.exceptions import AuthorizationError
from oura_ring_mcp.core.oauth import OuraOAuth, TokenSet

try:  # POSIX; without it, processes sharing a token file aren't serialised
    import fcntl
except ImportError:  # pragma: no cover - Windows
    fcntl = None  # type: ignore[assignment]

log = logging.getLogger(__name__)

# Refresh this long before the access token expires, so it doesn't lapse mid-request.
REFRESH_MARGIN = timedelta(minutes=5)
# How long to wait for another process that is refreshing the same token file.
LOCK_TIMEOUT_SECONDS = 30.0


class TokenSource(Protocol):
    can_refresh: bool

    async def get(self, *, refresh: bool = False, stale: str | None = None) -> str: ...


class StaticToken:
    """A token used as given, never refreshed (tests and one-off scripts)."""

    can_refresh = False

    def __init__(self, token: str) -> None:
        self._token = token

    async def get(self, *, refresh: bool = False, stale: str | None = None) -> str:
        return self._token


class TokenStore:
    """OAuth tokens in a JSON file readable only by the owner."""

    def __init__(self, path: Path) -> None:
        self.path = path

    @property
    def lock_path(self) -> Path:
        return self.path.with_name(f".{self.path.name}.lock")

    def load(self) -> TokenSet | None:
        try:
            return TokenSet.model_validate_json(self.path.read_text())
        except FileNotFoundError:
            return None
        except (OSError, ValidationError, json.JSONDecodeError):
            raise AuthorizationError("unreadable_token_file") from None

    def save(self, tokens: TokenSet) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        # A unique temp file (created 0600), so concurrent writers never share one.
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=f".{self.path.name}.")
        try:
            with os.fdopen(fd, "w") as f:
                f.write(tokens.model_dump_json())
            os.replace(tmp, self.path)  # atomic: a crash never leaves a half-written file
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            raise


@contextlib.asynccontextmanager
async def _file_lock(path: Path, timeout: float) -> AsyncIterator[None]:
    """Hold an exclusive lock on `path` across processes (best effort after `timeout`)."""
    if fcntl is None:
        yield
        return
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        deadline = time.monotonic() + timeout
        locked = False
        while not locked:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                locked = True
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    log.warning("Timed out waiting for %s; refreshing without it.", path)
                    break
                await asyncio.sleep(0.05)
        yield
    finally:
        os.close(fd)  # also releases the lock


class OAuthTokens:
    """Saved OAuth tokens, refreshed when near expiry or on demand.

    Oura's refresh tokens are single-use, so a refresh must never be lost or spent
    twice: refreshes are serialised across processes by a lock file, finish and save
    even if the tool call that started them is cancelled, and a failed save is retried
    instead of leaving a spent refresh token on disk.
    """

    can_refresh = True

    def __init__(
        self,
        oauth: OuraOAuth,
        store: TokenStore,
        *,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        lock_timeout: float = LOCK_TIMEOUT_SECONDS,
    ) -> None:
        self._oauth = oauth
        self._store = store
        self._now = now
        self._lock_timeout = lock_timeout
        self._lock = asyncio.Lock()
        self._tokens: TokenSet | None = None
        self._unsaved = False
        self._refreshing: asyncio.Task[None] | None = None

    async def get(self, *, refresh: bool = False, stale: str | None = None) -> str:
        """The current access token. `refresh` forces a new one, unless `stale` (the token
        that was rejected) has already been replaced."""
        async with self._lock:
            if self._refreshing is None:
                self._save_if_unsaved()
                self._adopt_from_disk()
                if self._tokens is None:
                    raise AuthorizationError("not_signed_in")
                if refresh and stale is not None and self._tokens.access_token != stale:
                    refresh = False  # already replaced since that request went out
                if refresh or self._tokens.expires_at - REFRESH_MARGIN <= self._now():
                    self._refreshing = asyncio.ensure_future(self._refresh(self._tokens))
                    # Mark any failure retrieved even if every waiter was cancelled.
                    self._refreshing.add_done_callback(
                        lambda t: None if t.cancelled() else t.exception()
                    )
            if self._refreshing is not None:
                task = self._refreshing
                try:
                    # Shielded: if this call is cancelled, the refresh still completes
                    # and saves the rotated refresh token.
                    await asyncio.shield(task)
                finally:
                    if task.done() and self._refreshing is task:
                        self._refreshing = None
            assert self._tokens is not None
            return self._tokens.access_token

    async def _refresh(self, current: TokenSet) -> None:
        async with _file_lock(self._store.lock_path, self._lock_timeout):
            # Another process may have refreshed while we waited for the lock.
            if self._newer_on_disk(current):
                return
            try:
                self._tokens = await self._oauth.refresh(current.refresh_token, now=self._now())
            except AuthorizationError:
                if self._newer_on_disk(current):  # lost a race to another process
                    return
                raise
            self._unsaved = True
            self._save_if_unsaved()

    def _newer_on_disk(self, current: TokenSet) -> bool:
        on_disk = self._store.load()
        if on_disk is not None and on_disk.refresh_token != current.refresh_token:
            self._tokens = on_disk
            return True
        return False

    def _adopt_from_disk(self) -> None:
        # Never let the file replace tokens we haven't managed to save yet.
        if self._unsaved:
            return
        on_disk = self._store.load()
        if on_disk is not None:
            self._tokens = on_disk

    def _save_if_unsaved(self) -> None:
        if not self._unsaved or self._tokens is None:
            return
        try:
            self._store.save(self._tokens)
        except OSError as exc:
            log.warning(
                "Could not save refreshed Oura tokens to %s (%s); will retry. If the server "
                "stops before a save succeeds, run `oura-ring-python-mcp auth` again.",
                self._store.path,
                exc.strerror or type(exc).__name__,
            )
        else:
            self._unsaved = False
