"""OuraService: date-range handling and error mapping over the Oura client."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Protocol, TypeVar

from mcp.server.mcpserver.exceptions import ToolError

from oura_ring_mcp import tracing
from oura_ring_mcp.core import (
    AccessDeniedError,
    APIError,
    AuthenticationError,
    Collection,
    HeartRateSample,
    NetworkError,
    PersonalInfo,
    RateLimitError,
    ResponseShapeError,
)

T = TypeVar("T")

DEFAULT_DAYS = 7
MAX_DAYS = 90
DEFAULT_HEART_RATE_WINDOW = timedelta(hours=24)
MAX_HEART_RATE_WINDOW = timedelta(days=7)


class OuraAPI(Protocol):
    """The subset of core.client.OuraClient that OuraService uses."""

    async def personal_info(self) -> PersonalInfo: ...
    async def documents(
        self, collection: Collection, start_date: date, end_date: date
    ) -> list[dict[str, Any]]: ...
    async def heart_rate(self, start: datetime, end: datetime) -> list[HeartRateSample]: ...


@dataclass(frozen=True)
class DateRange:
    start: date
    end: date  # inclusive


@dataclass(frozen=True)
class TimeRange:
    start: datetime
    end: datetime


def _parse_date(name: str, text: str) -> date:
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise ToolError(f"{name} {text!r} is not a date; use YYYY-MM-DD.") from None


def resolve_date_range(start: str | None, end: str | None, *, today: date) -> DateRange:
    """Inclusive day range; defaults to the DEFAULT_DAYS days ending today."""
    start_text, end_text = (start or "").strip(), (end or "").strip()
    end_day = _parse_date("end_date", end_text) if end_text else today
    if start_text:
        start_day = _parse_date("start_date", start_text)
    else:
        start_day = end_day - timedelta(days=DEFAULT_DAYS - 1)
    if start_day > end_day:
        raise ToolError(f"start_date {start_day} is after end_date {end_day}.")
    if (end_day - start_day).days + 1 > MAX_DAYS:
        raise ToolError(f"Date range is longer than {MAX_DAYS} days; ask for a shorter range.")
    return DateRange(start_day, end_day)


def _parse_datetime(name: str, text: str) -> datetime:
    try:
        value = datetime.fromisoformat(text)
    except ValueError:
        raise ToolError(
            f"{name} {text!r} is not a date-time; use ISO 8601, e.g. 2026-09-26T08:00:00."
        ) from None
    # No offset given: the caller means the server's local time.
    return value if value.tzinfo is not None else value.astimezone()


def resolve_time_range(start: str | None, end: str | None, *, now: datetime) -> TimeRange:
    """Heart rate window; defaults to the 24 hours ending now."""
    start_text, end_text = (start or "").strip(), (end or "").strip()
    end_at = _parse_datetime("end_datetime", end_text) if end_text else now
    if start_text:
        start_at = _parse_datetime("start_datetime", start_text)
    else:
        start_at = end_at - DEFAULT_HEART_RATE_WINDOW
    if start_at >= end_at:
        raise ToolError(f"start_datetime {start_at} is not before end_datetime {end_at}.")
    if end_at - start_at > MAX_HEART_RATE_WINDOW:
        raise ToolError(
            f"Heart rate window is longer than {MAX_HEART_RATE_WINDOW.days} days; "
            "ask for a shorter range."
        )
    return TimeRange(start_at, end_at)


def _to_tool_error(exc: Exception) -> ToolError | None:
    """Translate an Oura client error into a user-facing ToolError."""
    if isinstance(exc, AuthenticationError):
        return ToolError(
            "Oura rejected the access token. Check OURA_ACCESS_TOKEN; it may be expired or revoked."
        )
    if isinstance(exc, AccessDeniedError):
        return ToolError(
            "Oura denied access to this data. The Oura membership may have lapsed, "
            "or the token lacks the scope for it."
        )
    if isinstance(exc, RateLimitError):
        wait = f"in {exc.retry_after} seconds" if exc.retry_after is not None else "later"
        return ToolError(f"Rate limited by Oura. Try again {wait}.")
    if isinstance(exc, APIError):
        return ToolError(f"Oura API error {exc.status}.")
    if isinstance(exc, NetworkError):
        return ToolError(f"Could not reach Oura: {exc.kind}.")
    if isinstance(exc, ResponseShapeError):
        return ToolError(f"Oura returned unexpected data for {exc.call}.")
    return None


def _in_range(document: dict[str, Any], days: DateRange) -> bool:
    day = document.get("day")
    if not isinstance(day, str):
        return True
    try:
        return days.start <= date.fromisoformat(day) <= days.end
    except ValueError:
        return True


class OuraService:
    """Date-range defaults and validation, and error mapping, over an Oura client."""

    def __init__(
        self,
        client: OuraAPI,
        *,
        today: Callable[[], date] = date.today,
        now: Callable[[], datetime] = lambda: datetime.now().astimezone(),
    ) -> None:
        self._client = client
        self._today = today
        self._now = now

    async def personal_info(self) -> PersonalInfo:
        return await self._request("personal_info", self._client.personal_info)

    async def documents(
        self, collection: Collection, start_date: str | None, end_date: str | None
    ) -> tuple[DateRange, list[dict[str, Any]]]:
        days = resolve_date_range(start_date, end_date, today=self._today())
        # Oura's end_date is exclusive for some collections; ask for one more day and
        # trim, so the range is inclusive everywhere.
        documents = await self._request(
            collection.value,
            self._client.documents,
            collection,
            days.start,
            days.end + timedelta(days=1),
        )
        return days, [d for d in documents if _in_range(d, days)]

    async def heart_rate(
        self, start_datetime: str | None, end_datetime: str | None
    ) -> tuple[TimeRange, list[HeartRateSample]]:
        window = resolve_time_range(start_datetime, end_datetime, now=self._now())
        samples = await self._request(
            "heartrate", self._client.heart_rate, window.start, window.end
        )
        return window, samples

    async def _request(self, call: str, fn: Callable[..., Awaitable[T]], *args: object) -> T:
        async with tracing.span(f"oura.{call}"):
            try:
                return await fn(*args)
            except Exception as exc:
                tool_error = _to_tool_error(exc)
                if tool_error is None:
                    raise
                raise tool_error from exc
