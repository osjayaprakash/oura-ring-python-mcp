"""Settings loaded from environment variables."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from oura_ring_mcp.core.oauth import DEFAULT_SCOPES

_TRUTHY = {"true", "1", "yes"}

DEFAULT_REDIRECT_URI = "http://localhost:47651/callback"


class ConfigError(Exception):
    """Raised when required configuration is missing or invalid."""


@dataclass(frozen=True)
class Settings:
    client_id: str
    client_secret: str = field(repr=False)
    redirect_uri: str
    scopes: tuple[str, ...]
    token_file: Path
    timezone: ZoneInfo | None
    langfuse_enabled: bool
    langfuse_capture_data: bool


def _default_token_file(env: Mapping[str, str]) -> Path:
    config_home = env.get("XDG_CONFIG_HOME", "").strip()
    base = Path(config_home) if config_home else Path.home() / ".config"
    return base / "oura-ring-mcp" / "tokens.json"


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    """Build Settings from `env` (defaults to os.environ). Raises ConfigError."""
    env = os.environ if env is None else env

    client_id = env.get("OURA_CLIENT_ID", "").strip()
    client_secret = env.get("OURA_CLIENT_SECRET", "").strip()
    credentials = (("OURA_CLIENT_ID", client_id), ("OURA_CLIENT_SECRET", client_secret))
    missing = [name for name, value in credentials if not value]
    if missing:
        raise ConfigError(f"Missing required environment variable(s): {', '.join(missing)}")

    redirect_uri = env.get("OURA_REDIRECT_URI", "").strip() or DEFAULT_REDIRECT_URI
    scopes = tuple(env.get("OURA_SCOPES", "").replace(",", " ").split()) or DEFAULT_SCOPES
    token_file_text = env.get("OURA_TOKEN_FILE", "").strip()
    token_file = Path(token_file_text).expanduser() if token_file_text else _default_token_file(env)

    timezone_name = env.get("OURA_TIMEZONE", "").strip()
    try:
        timezone = ZoneInfo(timezone_name) if timezone_name else None
    except (ZoneInfoNotFoundError, ValueError):
        raise ConfigError(
            f"Invalid OURA_TIMEZONE {timezone_name!r}; use an IANA name such as Europe/London."
        ) from None

    langfuse_enabled = bool(
        env.get("LANGFUSE_PUBLIC_KEY", "").strip() and env.get("LANGFUSE_SECRET_KEY", "").strip()
    )
    capture = env.get("LANGFUSE_CAPTURE_DATA", "").strip().lower() in _TRUTHY

    return Settings(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
        scopes=scopes,
        token_file=token_file,
        timezone=timezone,
        langfuse_enabled=langfuse_enabled,
        langfuse_capture_data=capture,
    )
