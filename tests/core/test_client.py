from datetime import UTC, date, datetime

import httpx2
import pytest

from oura_ring_mcp.core import (
    AccessDeniedError,
    APIError,
    AuthenticationError,
    Collection,
    NetworkError,
    RateLimitError,
    ResponseShapeError,
)
from oura_ring_mcp.core.client import MAX_PAGES, OuraClient
from tests.core.mock_api import MockAPI, fixture

PERSONAL_INFO = "/v2/usercollection/personal_info"
DAILY_SLEEP = "/v2/usercollection/daily_sleep"
SLEEP = "/v2/usercollection/sleep"
HEARTRATE = "/v2/usercollection/heartrate"
START, END = date(2026, 9, 24), date(2026, 9, 26)


def make_client(api: MockAPI, token: str = "tok") -> OuraClient:
    return OuraClient(token, transport=api.transport())


async def test_requests_carry_bearer_token():
    api = MockAPI()
    api.on("GET", PERSONAL_INFO, json_body=fixture("personal_info"))
    async with make_client(api, "abc123") as client:
        await client.personal_info()
    [request] = api.requests
    assert str(request.url) == f"https://api.ouraring.com{PERSONAL_INFO}"
    assert request.headers["authorization"] == "Bearer abc123"


async def test_personal_info():
    api = MockAPI()
    api.on("GET", PERSONAL_INFO, json_body=fixture("personal_info"))
    async with make_client(api) as client:
        info = await client.personal_info()
    assert (info.id, info.age, info.height) == ("user-0001", 34, 1.78)


async def test_documents_send_dates_and_follow_next_token():
    api = MockAPI()
    api.on("GET", DAILY_SLEEP, json_body=fixture("daily_sleep_page1"))
    api.on("GET", DAILY_SLEEP, json_body=fixture("daily_sleep_page2"))
    async with make_client(api) as client:
        documents = await client.documents(Collection.DAILY_SLEEP, START, END)

    assert [d["score"] for d in documents] == [82, 74]
    first, second = api.requests
    assert dict(first.url.params) == {"start_date": "2026-09-24", "end_date": "2026-09-26"}
    assert dict(second.url.params) == {
        "start_date": "2026-09-24",
        "end_date": "2026-09-26",
        "next_token": "page-2",
    }


async def test_documents_are_returned_verbatim():
    api = MockAPI()
    api.on("GET", SLEEP, json_body=fixture("sleep"))
    async with make_client(api) as client:
        [period] = await client.documents(Collection.SLEEP, START, END)
    assert period["heart_rate"]["items"] == [60, 58, 55]


async def test_endless_pagination_is_a_shape_error():
    api = MockAPI()
    api.on("GET", DAILY_SLEEP, json_body={"data": [], "next_token": "again"})
    async with make_client(api) as client:
        with pytest.raises(ResponseShapeError) as info:
            await client.documents(Collection.DAILY_SLEEP, START, END)
    assert info.value.call == "daily_sleep"
    assert len(api.requests) == MAX_PAGES


async def test_heart_rate():
    api = MockAPI()
    api.on("GET", HEARTRATE, json_body=fixture("heartrate"))
    start = datetime(2026, 9, 26, 7, tzinfo=UTC)
    end = datetime(2026, 9, 26, 9, tzinfo=UTC)
    async with make_client(api) as client:
        samples = await client.heart_rate(start, end)
    assert [(s.bpm, s.source) for s in samples] == [(62, "awake"), (55, "rest")]
    assert samples[1].timestamp == datetime(2026, 9, 26, 8, tzinfo=UTC)
    assert dict(api.requests[0].url.params) == {
        "start_datetime": "2026-09-26T07:00:00+00:00",
        "end_datetime": "2026-09-26T09:00:00+00:00",
    }


@pytest.mark.parametrize("status, error", [(401, AuthenticationError), (403, AccessDeniedError)])
async def test_auth_statuses(status, error):
    api = MockAPI()
    api.on("GET", PERSONAL_INFO, status=status, json_body={"detail": "nope"})
    async with make_client(api) as client:
        with pytest.raises(error):
            await client.personal_info()


@pytest.mark.parametrize("header, expected", [({"Retry-After": "30"}, 30), ({}, None)])
async def test_rate_limit(header, expected):
    api = MockAPI()
    api.on("GET", DAILY_SLEEP, status=429, json_body={}, headers=header)
    async with make_client(api) as client:
        with pytest.raises(RateLimitError) as info:
            await client.documents(Collection.DAILY_SLEEP, START, END)
    assert info.value.retry_after == expected


@pytest.mark.parametrize("status", [400, 422, 500, 503])
async def test_other_statuses_are_api_errors(status):
    api = MockAPI()
    api.on("GET", PERSONAL_INFO, status=status, text="oops")
    async with make_client(api) as client:
        with pytest.raises(APIError) as info:
            await client.personal_info()
    assert info.value.status == status


@pytest.mark.parametrize(
    "exc, kind",
    [(httpx2.ConnectError("dns"), "ConnectError"), (httpx2.ReadTimeout("slow"), "ReadTimeout")],
)
async def test_network_errors(exc, kind):
    api = MockAPI()
    api.on("GET", PERSONAL_INFO, raises=exc)
    async with make_client(api) as client:
        with pytest.raises(NetworkError) as info:
            await client.personal_info()
    assert info.value.kind == kind


@pytest.mark.parametrize(
    "path, body, call",
    [
        (PERSONAL_INFO, {"age": 34}, "personal_info"),
        (PERSONAL_INFO, ["not", "an", "object"], "personal_info"),
        (DAILY_SLEEP, {"items": []}, "daily_sleep"),
        (DAILY_SLEEP, {"data": ["not-a-document"]}, "daily_sleep"),
        (HEARTRATE, {"data": [{"bpm": "fast"}]}, "heartrate"),
    ],
)
async def test_unexpected_shapes_name_the_call(path, body, call):
    api = MockAPI()
    api.on("GET", path, json_body=body)
    async with make_client(api) as client:
        with pytest.raises(ResponseShapeError) as info:
            if path == PERSONAL_INFO:
                await client.personal_info()
            elif path == HEARTRATE:
                await client.heart_rate(datetime(2026, 9, 26, tzinfo=UTC), datetime.now(UTC))
            else:
                await client.documents(Collection.DAILY_SLEEP, START, END)
    assert info.value.call == call


async def test_non_json_body():
    api = MockAPI()
    api.on("GET", PERSONAL_INFO, text="<html>maintenance</html>")
    async with make_client(api) as client:
        with pytest.raises(ResponseShapeError):
            await client.personal_info()


async def test_aclose_closes_http_client():
    client = make_client(MockAPI())
    await client.aclose()
    assert client._http.is_closed
