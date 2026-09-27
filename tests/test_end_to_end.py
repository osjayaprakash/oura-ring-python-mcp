"""MCP client -> tools -> OuraService -> OuraClient -> HTTP, with only the network faked."""

from datetime import UTC, date, datetime

import pytest
from mcp import Client

from oura_ring_mcp import server
from oura_ring_mcp.core import Collection
from oura_ring_mcp.core.client import OuraClient
from oura_ring_mcp.service import OuraService
from tests.core.mock_api import MockAPI, fixture

USERCOLLECTION = "/v2/usercollection"


@pytest.fixture
def api():
    api = MockAPI()
    api.on("GET", f"{USERCOLLECTION}/personal_info", json_body=fixture("personal_info"))
    api.on("GET", f"{USERCOLLECTION}/heartrate", json_body=fixture("heartrate"))
    api.on("GET", Collection.DAILY_SLEEP.path, json_body=fixture("daily_sleep_page1"))
    api.on("GET", Collection.DAILY_SLEEP.path, json_body=fixture("daily_sleep_page2"))
    for collection in Collection:
        if collection is not Collection.DAILY_SLEEP:
            api.on("GET", collection.path, json_body=fixture(collection.value))

    client = OuraClient("tok", transport=api.transport())
    server.set_service(
        OuraService(
            client,
            today=lambda: date(2026, 9, 26),
            now=lambda: datetime(2026, 9, 26, 12, tzinfo=UTC),
        )
    )
    yield api
    server.set_service(None)


async def call(name, arguments=None):
    async with Client(server.mcp) as client:
        result = await client.call_tool(name, arguments or {})
    assert not result.is_error, result.content
    return result.structured_content


async def test_personal_info(api):
    body = await call("get_personal_info")
    assert body == {
        "id": "user-0001",
        "age": 34,
        "weight": 70.5,
        "height": 1.78,
        "biological_sex": "male",
        "email": "me@example.com",
    }


async def test_daily_sleep_follows_pages_and_sends_padded_range(api):
    body = await call("get_daily_sleep")
    assert (body["start_date"], body["end_date"], body["count"]) == ("2026-09-20", "2026-09-26", 2)
    assert [(d["day"], d["score"]) for d in body["items"]] == [
        ("2026-09-24", 82),
        ("2026-09-25", 74),
    ]
    first, second = api.requests
    assert first.headers["authorization"] == "Bearer tok"
    assert dict(first.url.params) == {"start_date": "2026-09-20", "end_date": "2026-09-27"}
    assert second.url.params["next_token"] == "page-2"


async def test_explicit_range_trims_days_outside_it(api):
    body = await call("get_daily_sleep", {"start_date": "2026-09-25", "end_date": "2026-09-25"})
    assert [d["day"] for d in body["items"]] == ["2026-09-25"]


async def test_sleep_periods_keep_summaries_and_drop_series(api):
    [period] = (await call("get_sleep_periods"))["items"]
    assert period["total_sleep_duration"] == 26100
    assert period["average_hrv"] == 61
    assert period["readiness"]["score"] == 81
    for series in (
        "heart_rate",
        "hrv",
        "sleep_phase_5_min",
        "app_sleep_phase_5_min",
        "movement_30_sec",
    ):
        assert series not in period


@pytest.mark.parametrize(
    "tool, field, value",
    [
        ("get_daily_readiness", "score", 81),
        ("get_daily_activity", "steps", 11234),
        ("get_daily_stress", "stress_high", 3600),
        ("get_daily_spo2", "spo2_percentage", {"average": 96.8}),
        ("get_daily_resilience", "level", "solid"),
        ("get_workouts", "activity", "running"),
        ("get_sessions", "mood", "good"),
    ],
)
async def test_each_daily_tool_end_to_end(api, tool, field, value):
    [item] = (await call(tool))["items"]
    assert item[field] == value
    assert not any(isinstance(v, dict) and "items" in v for v in item.values())
    assert "class_5_min" not in item


async def test_heart_rate(api):
    body = await call("get_heart_rate")
    assert (body["count"], body["min_bpm"], body["max_bpm"], body["avg_bpm"]) == (2, 55, 62, 58.5)
    assert [s["source"] for s in body["samples"]] == ["rest", "awake"]
    assert dict(api.requests[0].url.params) == {
        "start_datetime": "2026-09-25T12:00:00+00:00",
        "end_datetime": "2026-09-26T12:00:00+00:00",
    }


async def test_http_error_becomes_tool_error(api):
    api.on("GET", f"{USERCOLLECTION}/personal_info", status=401, json_body={})
    api.on("GET", f"{USERCOLLECTION}/personal_info", status=401, json_body={})
    async with Client(server.mcp) as client:
        await client.call_tool("get_personal_info", {})  # consumes the 200 reply
        result = await client.call_tool("get_personal_info", {})
    assert result.is_error
    assert "Oura rejected the access token" in result.content[0].text
