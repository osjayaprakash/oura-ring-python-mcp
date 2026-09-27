from pathlib import Path

import pytest

from oura_ring_mcp.config import DEFAULT_REDIRECT_URI, ConfigError, load_settings
from oura_ring_mcp.core.oauth import DEFAULT_SCOPES

CLIENT = {"OURA_CLIENT_ID": "cid", "OURA_CLIENT_SECRET": "csecret"}


def test_defaults(monkeypatch):
    monkeypatch.setenv("HOME", "/home/me")
    settings = load_settings(CLIENT)
    assert (settings.client_id, settings.client_secret) == ("cid", "csecret")
    assert settings.redirect_uri == DEFAULT_REDIRECT_URI == "http://localhost:47651/callback"
    assert settings.scopes == DEFAULT_SCOPES
    assert "stress" in settings.scopes  # daily_resilience needs it
    assert settings.token_file == Path("/home/me/.config/oura-ring-mcp/tokens.json")
    assert settings.langfuse_enabled is False
    assert settings.langfuse_capture_data is False


def test_secret_not_in_repr():
    assert "csecret" not in repr(load_settings(CLIENT))


@pytest.mark.parametrize("value", [None, "", "   "])
def test_nothing_configured_names_both(value):
    env = {} if value is None else {"OURA_CLIENT_ID": value, "OURA_CLIENT_SECRET": value}
    with pytest.raises(ConfigError) as info:
        load_settings(env)
    assert "OURA_CLIENT_ID, OURA_CLIENT_SECRET" in str(info.value)


@pytest.mark.parametrize("missing", ["OURA_CLIENT_ID", "OURA_CLIENT_SECRET"])
def test_half_of_client_credentials(missing):
    env = {k: v for k, v in CLIENT.items() if k != missing}
    with pytest.raises(ConfigError) as info:
        load_settings(env)
    assert missing in str(info.value)
    assert ({"OURA_CLIENT_ID", "OURA_CLIENT_SECRET"} - {missing}).pop() not in str(info.value)


def test_access_token_variable_is_ignored():
    with pytest.raises(ConfigError):
        load_settings({"OURA_ACCESS_TOKEN": "tok"})


def test_credentials_whitespace_is_stripped():
    settings = load_settings({"OURA_CLIENT_ID": " cid\n", "OURA_CLIENT_SECRET": " csecret "})
    assert (settings.client_id, settings.client_secret) == ("cid", "csecret")


def test_overrides():
    settings = load_settings(
        {
            **CLIENT,
            "OURA_REDIRECT_URI": "https://example.com/cb",
            "OURA_SCOPES": "daily, heartrate personal",
            "OURA_TOKEN_FILE": "~/oura.json",
        }
    )
    assert settings.redirect_uri == "https://example.com/cb"
    assert settings.scopes == ("daily", "heartrate", "personal")
    assert settings.token_file == Path("~/oura.json").expanduser()


def test_token_file_follows_xdg_config_home():
    settings = load_settings({**CLIENT, "XDG_CONFIG_HOME": "/xdg"})
    assert settings.token_file == Path("/xdg/oura-ring-mcp/tokens.json")


@pytest.mark.parametrize(
    "public, secret, enabled",
    [("pk", "sk", True), ("pk", "", False), ("", "sk", False), ("", "", False)],
)
def test_langfuse_enabled_only_with_both_keys(public, secret, enabled):
    env = {**CLIENT, "LANGFUSE_PUBLIC_KEY": public, "LANGFUSE_SECRET_KEY": secret}
    assert load_settings(env).langfuse_enabled is enabled


@pytest.mark.parametrize(
    "raw, expected",
    [("true", True), ("1", True), ("YES", True), ("false", False), ("0", False), ("", False)],
)
def test_capture_flag_parsing(raw, expected):
    env = {**CLIENT, "LANGFUSE_CAPTURE_DATA": raw}
    assert load_settings(env).langfuse_capture_data is expected
