from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import httpx2
import pytest

from oura_ring_mcp.core import APIError, AuthorizationError, NetworkError, ResponseShapeError
from oura_ring_mcp.core.oauth import AUTHORIZE_URL, DEFAULT_SCOPES, OuraOAuth, TokenSet
from tests.core.mock_api import MockAPI

TOKEN = "/oauth/token"
NOW = datetime(2026, 9, 26, 12, tzinfo=UTC)
GRANT = {
    "token_type": "bearer",
    "access_token": "at-1",
    "expires_in": 86400,
    "refresh_token": "rt-1",
}


def make_oauth(api: MockAPI | None = None) -> OuraOAuth:
    transport = api.transport() if api else None
    return OuraOAuth("cid", "csecret", "http://localhost:47651/callback", transport=transport)


def form(request: httpx2.Request) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(request.content.decode()).items()}


def test_authorize_url():
    url = make_oauth().authorize_url("st4te")
    assert url.startswith(f"{AUTHORIZE_URL}?")
    query = {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}
    assert query == {
        "response_type": "code",
        "client_id": "cid",
        "redirect_uri": "http://localhost:47651/callback",
        "scope": " ".join(DEFAULT_SCOPES),
        "state": "st4te",
    }


async def test_exchange_code_posts_form_and_computes_expiry():
    api = MockAPI()
    api.on("POST", TOKEN, json_body=GRANT)
    tokens = await make_oauth(api).exchange_code("the-code", now=NOW)

    assert tokens == TokenSet(
        access_token="at-1", refresh_token="rt-1", expires_at=NOW + timedelta(days=1)
    )
    [request] = api.requests
    assert str(request.url) == "https://api.ouraring.com/oauth/token"
    assert request.headers["content-type"] == "application/x-www-form-urlencoded"
    assert form(request) == {
        "grant_type": "authorization_code",
        "code": "the-code",
        "redirect_uri": "http://localhost:47651/callback",
        "client_id": "cid",
        "client_secret": "csecret",
    }


async def test_refresh_uses_the_rotated_refresh_token():
    api = MockAPI()
    api.on("POST", TOKEN, json_body={**GRANT, "access_token": "at-2", "refresh_token": "rt-2"})
    tokens = await make_oauth(api).refresh("rt-1", now=NOW)
    assert (tokens.access_token, tokens.refresh_token) == ("at-2", "rt-2")
    assert form(api.requests[0]) == {
        "grant_type": "refresh_token",
        "refresh_token": "rt-1",
        "client_id": "cid",
        "client_secret": "csecret",
    }


async def test_refresh_without_new_refresh_token_keeps_the_old_one():
    api = MockAPI()
    api.on("POST", TOKEN, json_body={"access_token": "at-2", "expires_in": 60})
    tokens = await make_oauth(api).refresh("rt-1", now=NOW)
    assert tokens.refresh_token == "rt-1"


@pytest.mark.parametrize(
    "status, body, reason",
    [
        (400, {"error": "invalid_grant", "error_description": "used rt-1"}, "invalid_grant"),
        (401, {"error": "invalid_client"}, "invalid_client"),
        (400, {"error": "has spaces, maybe secrets"}, "HTTP 400"),
        (400, None, "HTTP 400"),
    ],
)
async def test_rejections_report_only_the_error_code(status, body, reason):
    api = MockAPI()
    if body is None:
        api.on("POST", TOKEN, status=status, text="bad")
    else:
        api.on("POST", TOKEN, status=status, json_body=body)
    with pytest.raises(AuthorizationError) as info:
        await make_oauth(api).refresh("rt-1")
    assert info.value.reason == reason
    assert "rt-1" not in str(info.value)


async def test_server_error_and_network_error():
    api = MockAPI()
    api.on("POST", TOKEN, status=503, text="down")
    with pytest.raises(APIError):
        await make_oauth(api).refresh("rt-1")
    api = MockAPI()
    api.on("POST", TOKEN, raises=httpx2.ConnectError("dns"))
    with pytest.raises(NetworkError):
        await make_oauth(api).refresh("rt-1")


@pytest.mark.parametrize("body", [{"expires_in": 60}, {"access_token": "a"}, ["x"]])
async def test_malformed_grant(body):
    api = MockAPI()
    api.on("POST", TOKEN, json_body=body)
    with pytest.raises(ResponseShapeError) as info:
        await make_oauth(api).exchange_code("c")
    assert info.value.call == "exchange_code"


def test_token_set_repr_hides_tokens():
    tokens = TokenSet(access_token="at-secret", refresh_token="rt-secret", expires_at=NOW)
    assert "secret" not in repr(tokens) and "secret" not in str(tokens)
