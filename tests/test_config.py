from pathlib import Path

import pytest

from oura_ring_mcp.config import DEFAULT_REDIRECT_URI, ConfigError, load_settings
from oura_ring_mcp.core.oauth import DEFAULT_SCOPES

TOKEN = {"OURA_ACCESS_TOKEN": "s3cret-token"}
CLIENT = {"OURA_CLIENT_ID": "cid", "OURA_CLIENT_SECRET": "csecret", "HOME": "/home/me"}


def test_access_token_mode():
    settings = load_settings(TOKEN)
    assert settings.access_token == "s3cret-token"
    assert settings.uses_oauth is False
    assert settings.langfuse_enabled is False
    assert settings.langfuse_capture_data is False


def test_oauth_mode_defaults(monkeypatch):
    monkeypatch.setenv("HOME", "/home/me")
    settings = load_settings({"OURA_CLIENT_ID": "cid", "OURA_CLIENT_SECRET": "csecret"})
    assert settings.uses_oauth is True
    assert (settings.client_id, settings.client_secret) == ("cid", "csecret")
    assert settings.redirect_uri == DEFAULT_REDIRECT_URI == "http://localhost:47651/callback"
    assert settings.scopes == DEFAULT_SCOPES
    assert settings.token_file == Path("/home/me/.config/oura-ring-mcp/tokens.json")


def test_access_token_wins_over_client_credentials():
    settings = load_settings({**CLIENT, **TOKEN})
    assert settings.uses_oauth is False


def test_secrets_not_in_repr():
    text = repr(load_settings({**CLIENT, **TOKEN}))
    assert "s3cret" not in text and "csecret" not in text


@pytest.mark.parametrize("value", [None, "", "   "])
def test_nothing_configured_names_both_options(value):
    env = {} if value is None else {"OURA_ACCESS_TOKEN": value}
    with pytest.raises(ConfigError) as info:
        load_settings(env)
    message = str(info.value)
    assert "OURA_CLIENT_ID" in message and "OURA_CLIENT_SECRET" in message
    assert "OURA_ACCESS_TOKEN" in message


@pytest.mark.parametrize("missing", ["OURA_CLIENT_ID", "OURA_CLIENT_SECRET"])
def test_half_of_client_credentials(missing):
    env = {k: v for k, v in CLIENT.items() if k != missing}
    with pytest.raises(ConfigError) as info:
        load_settings(env)
    assert missing in str(info.value)
    assert ({"OURA_CLIENT_ID", "OURA_CLIENT_SECRET"} - {missing}).pop() not in str(info.value)


def test_oauth_only_needs_client_credentials_even_with_token():
    with pytest.raises(ConfigError, match="OURA_CLIENT_ID") as info:
        load_settings(TOKEN, oauth_only=True)
    assert "OURA_ACCESS_TOKEN" not in str(info.value)
    settings = load_settings({**CLIENT, **TOKEN}, oauth_only=True)
    assert settings.uses_oauth is True


def test_token_whitespace_is_stripped():
    assert load_settings({"OURA_ACCESS_TOKEN": " tok\n"}).access_token == "tok"


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
    env = {**TOKEN, "LANGFUSE_PUBLIC_KEY": public, "LANGFUSE_SECRET_KEY": secret}
    assert load_settings(env).langfuse_enabled is enabled


@pytest.mark.parametrize(
    "raw, expected",
    [("true", True), ("1", True), ("YES", True), ("false", False), ("0", False), ("", False)],
)
def test_capture_flag_parsing(raw, expected):
    env = {**TOKEN, "LANGFUSE_CAPTURE_DATA": raw}
    assert load_settings(env).langfuse_capture_data is expected
