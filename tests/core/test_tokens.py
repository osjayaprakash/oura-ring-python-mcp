import stat
from datetime import UTC, datetime, timedelta

import pytest

from oura_ring_mcp.core import AuthorizationError
from oura_ring_mcp.core.oauth import TokenSet
from oura_ring_mcp.core.tokens import OAuthTokens, StaticToken, TokenStore

NOW = datetime(2026, 9, 26, 12, tzinfo=UTC)


def tokens(n: int, expires_in: timedelta = timedelta(hours=24)) -> TokenSet:
    return TokenSet(access_token=f"at-{n}", refresh_token=f"rt-{n}", expires_at=NOW + expires_in)


class FakeOAuth:
    def __init__(self):
        self.refreshed: list[str] = []
        self.fail: Exception | None = None

    async def refresh(self, refresh_token, *, now=None):
        if self.fail:
            raise self.fail
        self.refreshed.append(refresh_token)
        return tokens(len(self.refreshed) + 1)


@pytest.fixture
def store(tmp_path):
    return TokenStore(tmp_path / "cfg" / "tokens.json")


async def test_static_token():
    source = StaticToken("tok")
    assert source.can_refresh is False
    assert await source.get(refresh=True) == "tok"


def test_store_round_trip_is_private(store):
    assert store.load() is None
    store.save(tokens(1))
    assert store.load() == tokens(1)
    assert stat.S_IMODE(store.path.stat().st_mode) == 0o600
    assert not list(store.path.parent.glob(".*.tmp"))


def test_unreadable_store(store):
    store.path.parent.mkdir(parents=True)
    store.path.write_text("{not json")
    with pytest.raises(AuthorizationError, match="unreadable_token_file"):
        store.load()


async def test_not_signed_in(store):
    with pytest.raises(AuthorizationError) as info:
        await OAuthTokens(FakeOAuth(), store, now=lambda: NOW).get()
    assert info.value.reason == "not_signed_in"


async def test_fresh_token_is_used_without_refresh(store):
    store.save(tokens(1))
    oauth = FakeOAuth()
    source = OAuthTokens(oauth, store, now=lambda: NOW)
    assert await source.get() == "at-1"
    assert oauth.refreshed == []


@pytest.mark.parametrize("left", [timedelta(minutes=4), timedelta(0), timedelta(hours=-3)])
async def test_near_or_past_expiry_refreshes_and_saves_rotated_pair(store, left):
    store.save(tokens(1, expires_in=left))
    oauth = FakeOAuth()
    source = OAuthTokens(oauth, store, now=lambda: NOW)
    assert await source.get() == "at-2"
    assert oauth.refreshed == ["rt-1"]
    assert store.load().refresh_token == "rt-2"  # single-use: the new one is persisted
    assert await source.get() == "at-2"
    assert oauth.refreshed == ["rt-1"]


async def test_forced_refresh(store):
    store.save(tokens(1))
    oauth = FakeOAuth()
    assert await OAuthTokens(oauth, store, now=lambda: NOW).get(refresh=True) == "at-2"


async def test_picks_up_tokens_refreshed_by_another_process(store):
    store.save(tokens(1, expires_in=timedelta(hours=1)))
    oauth = FakeOAuth()
    source = OAuthTokens(oauth, store, now=lambda: NOW)
    assert await source.get() == "at-1"

    store.save(tokens(9, expires_in=timedelta(hours=24)))  # another server refreshed
    assert await source.get(refresh=True) == "at-9"
    assert oauth.refreshed == []  # didn't burn the other process's refresh token


async def test_concurrent_callers_refresh_once(store):
    import asyncio

    store.save(tokens(1, expires_in=timedelta(0)))
    oauth = FakeOAuth()
    source = OAuthTokens(oauth, store, now=lambda: NOW)
    assert set(await asyncio.gather(*(source.get() for _ in range(5)))) == {"at-2"}
    assert oauth.refreshed == ["rt-1"]


async def test_refresh_failure_keeps_saved_tokens(store):
    store.save(tokens(1, expires_in=timedelta(0)))
    oauth = FakeOAuth()
    oauth.fail = AuthorizationError("invalid_grant")
    with pytest.raises(AuthorizationError):
        await OAuthTokens(oauth, store, now=lambda: NOW).get()
    assert store.load() == tokens(1, expires_in=timedelta(0))
