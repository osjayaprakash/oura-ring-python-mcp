import pytest

from oura_ring_mcp.config import ConfigError, load_settings

CREDS = {"OURA_ACCESS_TOKEN": "s3cret-token"}


def test_minimal_env_uses_defaults():
    settings = load_settings(CREDS)
    assert settings.access_token == "s3cret-token"
    assert settings.langfuse_enabled is False
    assert settings.langfuse_capture_data is False


def test_token_not_in_repr():
    assert "s3cret" not in repr(load_settings(CREDS))


@pytest.mark.parametrize("value", [None, "", "   "])
def test_missing_or_blank_token_raises(value):
    env = {} if value is None else {"OURA_ACCESS_TOKEN": value}
    with pytest.raises(ConfigError, match="OURA_ACCESS_TOKEN"):
        load_settings(env)


def test_token_whitespace_is_stripped():
    assert load_settings({"OURA_ACCESS_TOKEN": " tok\n"}).access_token == "tok"


@pytest.mark.parametrize(
    "public, secret, enabled",
    [("pk", "sk", True), ("pk", "", False), ("", "sk", False), ("", "", False)],
)
def test_langfuse_enabled_only_with_both_keys(public, secret, enabled):
    env = {**CREDS, "LANGFUSE_PUBLIC_KEY": public, "LANGFUSE_SECRET_KEY": secret}
    assert load_settings(env).langfuse_enabled is enabled


@pytest.mark.parametrize(
    "raw, expected",
    [("true", True), ("1", True), ("YES", True), ("false", False), ("0", False), ("", False)],
)
def test_capture_flag_parsing(raw, expected):
    env = {**CREDS, "LANGFUSE_CAPTURE_DATA": raw}
    assert load_settings(env).langfuse_capture_data is expected
