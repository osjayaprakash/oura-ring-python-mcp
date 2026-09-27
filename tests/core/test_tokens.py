import asyncio
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
    """Like Oura: each refresh token works once."""

    def __init__(self, *, delay: float = 0.0):
        self.refreshed: list[str] = []
        self.fail: Exception | None = None
        self.delay = delay

    async def refresh(self, refresh_token, *, now=None):
        if self.fail:
            raise self.fail
        if refresh_token in self.refreshed:
            raise AuthorizationError("invalid_grant")
        self.refreshed.append(refresh_token)
        if self.delay:
            await asyncio.sleep(self.delay)
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
    # at-1 was rejected, but it has already been replaced: use at-9, don't refresh.
    assert await source.get(refresh=True, stale="at-1") == "at-9"
    assert oauth.refreshed == []  # didn't burn the other process's refresh token


async def test_concurrent_callers_refresh_once(store):
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


async def test_two_processes_sharing_a_token_file_refresh_once(store):
    # Claude Desktop and Claude Code each run a server over the same file.
    store.save(tokens(1, expires_in=timedelta(0)))
    oauth = FakeOAuth(delay=0.05)
    desktop = OAuthTokens(oauth, TokenStore(store.path), now=lambda: NOW)
    code = OAuthTokens(oauth, TokenStore(store.path), now=lambda: NOW)
    assert await asyncio.gather(desktop.get(), code.get()) == ["at-2", "at-2"]
    assert oauth.refreshed == ["rt-1"]  # the single-use token was spent once
    assert store.load().refresh_token == "rt-2"


async def test_lost_refresh_race_uses_the_winners_tokens(store):
    store.save(tokens(1, expires_in=timedelta(0)))
    oauth = FakeOAuth()
    oauth.refreshed.append("rt-1")  # another process already spent rt-1 ...
    store_other = TokenStore(store.path)
    source = OAuthTokens(oauth, store, now=lambda: NOW)
    source._tokens = tokens(1, expires_in=timedelta(0))

    async def refresh_then_winner_saves(refresh_token, *, now=None):
        store_other.save(tokens(7))  # ... and saved its result just before our refresh failed
        raise AuthorizationError("invalid_grant")

    oauth.refresh = refresh_then_winner_saves
    source._adopt_from_disk = lambda: None  # we had read the file before the winner saved
    assert await source.get() == "at-7"


async def test_failed_save_keeps_new_tokens_and_retries(store, monkeypatch, caplog):
    store.save(tokens(1, expires_in=timedelta(0)))
    oauth = FakeOAuth()
    source = OAuthTokens(oauth, store, now=lambda: NOW)
    real_save = store.save

    def disk_full(_tokens):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(store, "save", disk_full)
    assert await source.get() == "at-2"  # the call still succeeds
    assert "will retry" in caplog.text
    assert store.load().refresh_token == "rt-1"  # file still has the old pair ...
    assert await source.get() == "at-2"  # ... which must not replace the unsaved new one
    assert oauth.refreshed == ["rt-1"]

    monkeypatch.setattr(store, "save", real_save)
    assert await source.get() == "at-2"
    assert store.load().refresh_token == "rt-2"  # retried and saved


async def test_cancelled_call_still_saves_the_rotated_token(store):
    store.save(tokens(1, expires_in=timedelta(0)))
    oauth = FakeOAuth(delay=0.1)
    source = OAuthTokens(oauth, store, now=lambda: NOW)
    call = asyncio.ensure_future(source.get())
    await asyncio.sleep(0.02)  # refresh is in flight
    call.cancel()
    with pytest.raises(asyncio.CancelledError):
        await call
    await asyncio.sleep(0.2)
    assert store.load().refresh_token == "rt-2"  # rt-1 was spent, and rt-2 was kept
    assert await source.get() == "at-2"
    assert oauth.refreshed == ["rt-1"]


async def test_stale_rejection_after_refresh_does_not_refresh_again(store):
    store.save(tokens(1, expires_in=timedelta(0)))
    oauth = FakeOAuth()
    source = OAuthTokens(oauth, store, now=lambda: NOW)
    assert await source.get() == "at-2"
    # A request sent with at-1 before the refresh now comes back 401.
    assert await source.get(refresh=True, stale="at-1") == "at-2"
    assert oauth.refreshed == ["rt-1"]
