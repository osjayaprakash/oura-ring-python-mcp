"""Settings loaded from environment variables."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field

_TRUTHY = {"true", "1", "yes"}


class ConfigError(Exception):
    """Raised when required configuration is missing or invalid."""


@dataclass(frozen=True)
class Settings:
    access_token: str = field(repr=False)
    langfuse_enabled: bool
    langfuse_capture_data: bool


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    """Build Settings from `env` (defaults to os.environ). Raises ConfigError."""
    env = os.environ if env is None else env

    access_token = env.get("OURA_ACCESS_TOKEN", "").strip()
    if not access_token:
        raise ConfigError("Missing required environment variable(s): OURA_ACCESS_TOKEN")

    langfuse_enabled = bool(
        env.get("LANGFUSE_PUBLIC_KEY", "").strip() and env.get("LANGFUSE_SECRET_KEY", "").strip()
    )
    capture = env.get("LANGFUSE_CAPTURE_DATA", "").strip().lower() in _TRUTHY

    return Settings(
        access_token=access_token,
        langfuse_enabled=langfuse_enabled,
        langfuse_capture_data=capture,
    )
