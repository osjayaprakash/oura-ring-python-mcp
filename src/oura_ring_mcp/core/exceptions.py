"""Errors raised by OuraClient. Messages never contain health data or the token."""

from __future__ import annotations


class OuraError(Exception):
    """Base class for every client error."""


class AuthenticationError(OuraError):
    """The access token is missing, invalid, expired or revoked (HTTP 401)."""


class AccessDeniedError(OuraError):
    """HTTP 403: membership lapsed, or the token lacks the scope for this data."""


class RateLimitError(OuraError):
    def __init__(self, retry_after: int | None) -> None:
        self.retry_after = retry_after
        super().__init__(f"Rate limited (retry after {retry_after})")


class APIError(OuraError):
    """Unexpected HTTP status."""

    def __init__(self, status: int) -> None:
        self.status = status
        super().__init__(f"Oura API error {status}")


class NetworkError(OuraError):
    """Connection failure or timeout; `kind` is the transport error class name."""

    def __init__(self, kind: str) -> None:
        self.kind = kind
        super().__init__(f"Network error: {kind}")


class ResponseShapeError(OuraError):
    """A response did not have the expected shape; `call` names the client call."""

    def __init__(self, call: str) -> None:
        self.call = call
        super().__init__(f"Unexpected response shape from {call}")
