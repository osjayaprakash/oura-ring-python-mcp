from datetime import UTC, date, datetime

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from oura_ring_mcp.core import (
    AccessDeniedError,
    APIError,
    AuthenticationError,
    AuthorizationError,
    Collection,
    MissingScopeError,
    NetworkError,
    RateLimitError,
    ResponseShapeError,
)
from oura_ring_mcp.service import OuraService
from tests.fakes import ME, FakeOuraClient

TODAY = date(2026, 9, 26)
NOW = datetime(2026, 9, 26, 12, 0, tzinfo=UTC)


def make_service(client: FakeOuraClient) -> OuraService:
    return OuraService(client, today=lambda: TODAY, now=lambda: NOW)


async def test_personal_info():
    assert await make_service(FakeOuraClient()).personal_info() is ME


async def test_documents_ask_for_one_extra_day_and_trim_to_the_range():
    client = FakeOuraClient(
        {
            Collection.DAILY_SLEEP: [
                {"day": "2026-09-19", "score": 1},
                {"day": "2026-09-20", "score": 2},
                {"day": "2026-09-26", "score": 3},
                {"day": "2026-09-27", "score": 4},
                {"score": 5},  # no day: kept
            ]
        }
    )
    days, documents = await make_service(client).documents(Collection.DAILY_SLEEP, None, None)

    assert (days.start, days.end) == (date(2026, 9, 20), TODAY)
    assert client.calls == [
        ("documents", Collection.DAILY_SLEEP, date(2026, 9, 20), date(2026, 9, 27))
    ]
    assert [d["score"] for d in documents] == [2, 3, 5]


async def test_invalid_range_makes_no_api_call():
    client = FakeOuraClient()
    with pytest.raises(ToolError, match="not a date"):
        await make_service(client).documents(Collection.SLEEP, "yesterday", None)
    assert client.calls == []


async def test_heart_rate_uses_resolved_window():
    client = FakeOuraClient()
    window, samples = await make_service(client).heart_rate(None, None)
    assert window.end == NOW
    assert client.calls == [("heart_rate", window.start, NOW)]
    assert len(samples) == 2


@pytest.mark.parametrize(
    "error, message",
    [
        (AuthenticationError("401"), "Run `oura-ring-mcp auth` to sign in again."),
        (
            MissingScopeError("stress"),
            "Allow `stress` for the application (and in OURA_SCOPES if you set it), "
            "then run `oura-ring-mcp auth` again.",
        ),
        (
            AuthorizationError("invalid_grant"),
            "(invalid_grant). Run `oura-ring-mcp auth` to sign in again.",
        ),
        (AccessDeniedError("403"), "or the token lacks the scope for it."),
        (RateLimitError(30), "Try again in 30 seconds."),
        (RateLimitError(None), "Try again later."),
        (APIError(500), "Oura API error 500."),
        (NetworkError("ConnectError"), "Could not reach Oura: ConnectError."),
        (ResponseShapeError("daily_sleep"), "Oura returned unexpected data for daily_sleep."),
    ],
)
async def test_client_errors_are_mapped(error, message):
    client = FakeOuraClient()
    client.fail_next["documents"] = [error]
    with pytest.raises(ToolError) as info:
        await make_service(client).documents(Collection.DAILY_SLEEP, None, None)
    assert str(info.value).endswith(message)
    assert info.value.__cause__ is error


async def test_errors_are_mapped_for_every_call():
    client = FakeOuraClient()
    client.fail_next["personal_info"] = [AuthenticationError("401")]
    client.fail_next["heart_rate"] = [AccessDeniedError("403")]
    service = make_service(client)
    with pytest.raises(ToolError, match="sign in again"):
        await service.personal_info()
    with pytest.raises(ToolError, match="denied access"):
        await service.heart_rate(None, None)


async def test_unexpected_errors_propagate_unchanged():
    client = FakeOuraClient()
    client.fail_next["personal_info"] = [KeyError("data")]
    with pytest.raises(KeyError):
        await make_service(client).personal_info()
