"""MCP server exposing Oura Ring data as read-only tools."""

from __future__ import annotations

import argparse
import atexit
import logging
import sys
from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations
from pydantic import Field

from oura_ring_mcp import formatting, tracing
from oura_ring_mcp.config import ConfigError, Settings, load_settings
from oura_ring_mcp.core import AuthorizationError, Collection, OuraError
from oura_ring_mcp.core.client import OuraClient
from oura_ring_mcp.core.oauth import OuraOAuth
from oura_ring_mcp.core.tokens import OAuthTokens, TokenStore
from oura_ring_mcp.login import LoginError, run_login
from oura_ring_mcp.service import OuraService

mcp = MCPServer(
    "oura",
    instructions=(
        "Read-only access to the user's Oura Ring data: sleep, readiness, activity, stress, "
        "SpO2, resilience, workouts, sessions and heart rate. "
        "Daily tools take an inclusive start_date/end_date (YYYY-MM-DD) and default to the "
        "7 days ending today; each result echoes the range it covers. "
        "`day` is the user's local calendar day; scores run 0-100; durations are seconds."
    ),
)

_READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=True)

StartDate = Annotated[
    str | None,
    Field(description="First day, YYYY-MM-DD. Omit for 6 days before end_date."),
]
EndDate = Annotated[
    str | None,
    Field(description="Last day (inclusive), YYYY-MM-DD. Omit for today."),
]
StartDatetime = Annotated[
    str | None,
    Field(
        description=(
            "Window start, ISO 8601 (e.g. 2026-09-26T08:00:00+02:00; no offset means the "
            "server's local time). Omit for 24 hours before end_datetime."
        )
    ),
]
EndDatetime = Annotated[
    str | None,
    Field(description="Window end, ISO 8601. Omit for now."),
]

_service: OuraService | None = None


def set_service(service: OuraService | None) -> None:
    global _service
    _service = service


def _get_service() -> OuraService:
    if _service is None:
        raise RuntimeError("OuraService is not configured; call main() or set_service().")
    return _service


async def _documents(
    collection: Collection, start_date: str | None, end_date: str | None
) -> dict[str, Any]:
    days, documents = await _get_service().documents(collection, start_date, end_date)
    return formatting.documents_response(days, documents)


@mcp.tool(annotations=_READ_ONLY)
@tracing.traced("get_personal_info")
async def get_personal_info() -> dict[str, Any]:
    """The Oura user's profile: age, weight (kg), height (m), biological sex and email."""
    info = await _get_service().personal_info()
    return formatting.personal_info_to_dict(info)


@mcp.tool(annotations=_READ_ONLY)
@tracing.traced("get_daily_sleep")
async def get_daily_sleep(start_date: StartDate = None, end_date: EndDate = None) -> dict[str, Any]:
    """Daily sleep score (0-100) with its contributors (deep sleep, efficiency, latency,
    REM, restfulness, timing, total sleep), one item per day."""
    return await _documents(Collection.DAILY_SLEEP, start_date, end_date)


@mcp.tool(annotations=_READ_ONLY)
@tracing.traced("get_sleep_periods")
async def get_sleep_periods(
    start_date: StartDate = None, end_date: EndDate = None
) -> dict[str, Any]:
    """Each sleep period (night sleep and naps): bedtimes, time in deep/light/REM/awake
    (seconds), efficiency, latency, average and lowest heart rate, average HRV."""
    return await _documents(Collection.SLEEP, start_date, end_date)


@mcp.tool(annotations=_READ_ONLY)
@tracing.traced("get_daily_readiness")
async def get_daily_readiness(
    start_date: StartDate = None, end_date: EndDate = None
) -> dict[str, Any]:
    """Daily readiness score (0-100) with contributors (HRV balance, resting heart rate,
    recovery, sleep balance, activity balance) and body temperature deviation (°C)."""
    return await _documents(Collection.DAILY_READINESS, start_date, end_date)


@mcp.tool(annotations=_READ_ONLY)
@tracing.traced("get_daily_activity")
async def get_daily_activity(
    start_date: StartDate = None, end_date: EndDate = None
) -> dict[str, Any]:
    """Daily activity score (0-100), steps, active and total calories, walking-equivalent
    distance (m), and time at each activity level (seconds)."""
    return await _documents(Collection.DAILY_ACTIVITY, start_date, end_date)


@mcp.tool(annotations=_READ_ONLY)
@tracing.traced("get_daily_stress")
async def get_daily_stress(
    start_date: StartDate = None, end_date: EndDate = None
) -> dict[str, Any]:
    """Daily time spent in high stress and in recovery (seconds), and the day summary."""
    return await _documents(Collection.DAILY_STRESS, start_date, end_date)


@mcp.tool(annotations=_READ_ONLY)
@tracing.traced("get_daily_spo2")
async def get_daily_spo2(start_date: StartDate = None, end_date: EndDate = None) -> dict[str, Any]:
    """Nightly average blood oxygen saturation (%) and breathing disturbance index."""
    return await _documents(Collection.DAILY_SPO2, start_date, end_date)


@mcp.tool(annotations=_READ_ONLY)
@tracing.traced("get_daily_resilience")
async def get_daily_resilience(
    start_date: StartDate = None, end_date: EndDate = None
) -> dict[str, Any]:
    """Daily resilience level (limited to exceptional) with sleep and daytime recovery
    and stress contributors."""
    return await _documents(Collection.DAILY_RESILIENCE, start_date, end_date)


@mcp.tool(annotations=_READ_ONLY)
@tracing.traced("get_workouts")
async def get_workouts(start_date: StartDate = None, end_date: EndDate = None) -> dict[str, Any]:
    """Workouts: activity type, start and end time, intensity, calories and distance (m)."""
    return await _documents(Collection.WORKOUT, start_date, end_date)


@mcp.tool(annotations=_READ_ONLY)
@tracing.traced("get_sessions")
async def get_sessions(start_date: StartDate = None, end_date: EndDate = None) -> dict[str, Any]:
    """Guided or unguided sessions (meditation, breathing, rest, naps) with start, end
    and mood."""
    return await _documents(Collection.SESSION, start_date, end_date)


@mcp.tool(annotations=_READ_ONLY)
@tracing.traced("get_heart_rate")
async def get_heart_rate(
    start_datetime: StartDatetime = None, end_datetime: EndDatetime = None
) -> dict[str, Any]:
    """Heart rate samples (bpm, source such as rest/sleep/workout) in a window of up to
    7 days, oldest first, with min, max and average bpm."""
    window, samples = await _get_service().heart_rate(start_datetime, end_datetime)
    return formatting.heart_rate_response(window, samples)


def build_client(settings: Settings) -> OuraClient:
    if not settings.uses_oauth:
        assert settings.access_token is not None
        return OuraClient(settings.access_token)
    assert settings.client_id and settings.client_secret
    oauth = OuraOAuth(
        settings.client_id, settings.client_secret, settings.redirect_uri, scopes=settings.scopes
    )
    return OuraClient(OAuthTokens(oauth, TokenStore(settings.token_file)))


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="oura-ring-mcp", description="MCP server for Oura Ring data (stdio)."
    )
    commands = parser.add_subparsers(dest="command")
    auth = commands.add_parser("auth", help="sign in to Oura in the browser and save tokens")
    auth.add_argument(
        "--paste",
        action="store_true",
        help="paste the redirect URL instead of catching it on localhost (Docker, SSH)",
    )
    return parser.parse_args(argv)


def _fail(message: object) -> None:
    print(f"oura-ring-mcp: {message}", file=sys.stderr)
    sys.exit(1)


_AUTH_HINTS = {
    "invalid_client": "Check OURA_CLIENT_ID and OURA_CLIENT_SECRET.",
    "invalid_grant": "The sign-in code expired or was already used; run `auth` again.",
    "invalid_request": "Check that OURA_REDIRECT_URI matches the application's redirect URI.",
}


def _auth(paste: bool) -> None:
    try:
        run_login(load_settings(oauth_only=True), paste=paste, out=sys.stderr)
    except AuthorizationError as exc:
        _fail(f"{exc}. {_AUTH_HINTS.get(exc.reason, '')}".rstrip())
    except (ConfigError, LoginError, OuraError) as exc:
        _fail(exc)


def main(argv: list[str] | None = None) -> None:
    # stdout carries the MCP protocol; every log line must go to stderr.
    logging.basicConfig(stream=sys.stderr, level=logging.WARNING)
    args = _parse_args(argv)
    if args.command == "auth":
        _auth(args.paste)
        return

    try:
        settings = load_settings()
    except ConfigError as exc:
        _fail(exc)
    if settings.uses_oauth and not settings.token_file.exists():
        _fail(f"Not signed in to Oura (no {settings.token_file}). Run `oura-ring-mcp auth` first.")

    tracing.configure(settings)
    atexit.register(tracing.shutdown)
    set_service(OuraService(build_client(settings)))
    mcp.run("stdio")
