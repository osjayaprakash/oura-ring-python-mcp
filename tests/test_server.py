import json
from datetime import UTC, date, datetime

import pytest
from mcp import Client

from oura_ring_mcp import server
from oura_ring_mcp.core import Collection
from oura_ring_mcp.core.client import OuraClient
from oura_ring_mcp.service import OuraService
from tests.fakes import FakeOuraClient

DAILY_TOOLS = {
    "get_daily_sleep": Collection.DAILY_SLEEP,
    "get_sleep_periods": Collection.SLEEP,
    "get_daily_readiness": Collection.DAILY_READINESS,
    "get_daily_activity": Collection.DAILY_ACTIVITY,
    "get_daily_stress": Collection.DAILY_STRESS,
    "get_daily_spo2": Collection.DAILY_SPO2,
    "get_daily_resilience": Collection.DAILY_RESILIENCE,
    "get_workouts": Collection.WORKOUT,
    "get_sessions": Collection.SESSION,
}
TOOLS = {"get_personal_info", "get_heart_rate", *DAILY_TOOLS}


@pytest.fixture
def fake_client():
    client = FakeOuraClient({Collection.DAILY_READINESS: [{"day": "2026-09-25", "score": 81}]})
    server.set_service(
        OuraService(
            client,
            today=lambda: date(2026, 9, 26),
            now=lambda: datetime(2026, 9, 26, 12, tzinfo=UTC),
        )
    )
    yield client
    server.set_service(None)


async def call(name, arguments=None):
    async with Client(server.mcp) as client:
        return await client.call_tool(name, arguments or {})


async def test_lists_read_only_tools_with_optional_ranges(fake_client):
    async with Client(server.mcp) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
    assert set(tools) == TOOLS
    assert all(t.annotations.read_only_hint for t in tools.values())
    assert tools["get_personal_info"].input_schema.get("properties", {}) == {}
    for name in DAILY_TOOLS:
        schema = tools[name].input_schema
        assert list(schema["properties"]) == ["start_date", "end_date"]
        assert schema.get("required", []) == []
    schema = tools["get_heart_rate"].input_schema
    assert list(schema["properties"]) == ["start_datetime", "end_datetime"]


@pytest.mark.parametrize("tool, collection", DAILY_TOOLS.items())
async def test_each_daily_tool_reads_its_collection(fake_client, tool, collection):
    result = await call(tool, {"start_date": "2026-09-25", "end_date": "2026-09-25"})
    assert not result.is_error, result.content
    assert fake_client.calls[-1] == ("documents", collection, date(2026, 9, 25), date(2026, 9, 26))


async def test_daily_readiness_result(fake_client):
    result = await call("get_daily_readiness")
    body = result.structured_content
    assert (body["start_date"], body["end_date"]) == ("2026-09-20", "2026-09-26")
    assert body["items"] == [{"day": "2026-09-25", "score": 81}]
    assert json.loads(result.content[0].text) == body


async def test_get_personal_info(fake_client):
    result = await call("get_personal_info")
    assert result.structured_content["age"] == 34


async def test_get_heart_rate(fake_client):
    result = await call("get_heart_rate", {"start_datetime": "2026-09-26T07:00:00+00:00"})
    body = result.structured_content
    assert [s["bpm"] for s in body["samples"]] == [55, 62]
    assert body["end_datetime"] == "2026-09-26T12:00:00+00:00"


async def test_tool_error_is_reported_not_raised(fake_client):
    result = await call("get_daily_sleep", {"start_date": "2026-01-01"})
    assert result.is_error
    assert "longer than 90 days" in result.content[0].text


def _clear_oura_env(monkeypatch):
    for name in ("OURA_ACCESS_TOKEN", "OURA_CLIENT_ID", "OURA_CLIENT_SECRET", "OURA_TOKEN_FILE"):
        monkeypatch.delenv(name, raising=False)


async def test_main_exits_when_nothing_configured(monkeypatch, capsys):
    _clear_oura_env(monkeypatch)
    with pytest.raises(SystemExit) as info:
        server.main([])
    assert info.value.code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "OURA_CLIENT_ID" in captured.err and "OURA_ACCESS_TOKEN" in captured.err


async def test_main_exits_when_oauth_not_signed_in(monkeypatch, capsys, tmp_path):
    _clear_oura_env(monkeypatch)
    monkeypatch.setenv("OURA_CLIENT_ID", "cid")
    monkeypatch.setenv("OURA_CLIENT_SECRET", "csecret")
    monkeypatch.setenv("OURA_TOKEN_FILE", str(tmp_path / "tokens.json"))
    with pytest.raises(SystemExit) as info:
        server.main([])
    assert info.value.code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Run `oura-ring-mcp auth` first" in captured.err


async def test_auth_command_needs_client_credentials(monkeypatch, capsys):
    _clear_oura_env(monkeypatch)
    monkeypatch.setenv("OURA_ACCESS_TOKEN", "tok")
    with pytest.raises(SystemExit) as info:
        server.main(["auth"])
    assert info.value.code == 1
    assert "OURA_CLIENT_ID" in capsys.readouterr().err


async def test_auth_command_explains_oauth_errors(monkeypatch, capsys):
    from oura_ring_mcp.core import AuthorizationError

    _clear_oura_env(monkeypatch)
    monkeypatch.setenv("OURA_CLIENT_ID", "cid")
    monkeypatch.setenv("OURA_CLIENT_SECRET", "csecret")

    def reject(settings, *, paste, out):
        raise AuthorizationError("invalid_client")

    monkeypatch.setattr(server, "run_login", reject)
    with pytest.raises(SystemExit) as info:
        server.main(["auth"])
    assert info.value.code == 1
    err = capsys.readouterr().err
    assert "invalid_client. Check OURA_CLIENT_ID and OURA_CLIENT_SECRET." in err


async def test_auth_command_runs_login(monkeypatch):
    _clear_oura_env(monkeypatch)
    monkeypatch.setenv("OURA_CLIENT_ID", "cid")
    monkeypatch.setenv("OURA_CLIENT_SECRET", "csecret")
    seen = {}
    monkeypatch.setattr(
        server, "run_login", lambda settings, *, paste, out: seen.update(paste=paste)
    )
    server.main(["auth", "--paste"])
    assert seen == {"paste": True}


async def test_build_client_with_access_token():
    from oura_ring_mcp.config import load_settings
    from oura_ring_mcp.core.tokens import StaticToken

    client = server.build_client(load_settings({"OURA_ACCESS_TOKEN": "tok"}))
    assert isinstance(client, OuraClient)
    assert isinstance(client._auth, StaticToken)
    assert await client._auth.get() == "tok"
    await client.aclose()


async def test_build_client_with_oauth(tmp_path):
    from oura_ring_mcp.config import load_settings
    from oura_ring_mcp.core.tokens import OAuthTokens

    settings = load_settings(
        {
            "OURA_CLIENT_ID": "cid",
            "OURA_CLIENT_SECRET": "csecret",
            "OURA_TOKEN_FILE": str(tmp_path / "t.json"),
        }
    )
    client = server.build_client(settings)
    assert isinstance(client._auth, OAuthTokens)
    await client.aclose()
