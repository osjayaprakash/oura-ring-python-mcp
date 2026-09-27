"""Pydantic models for the Oura payloads this server reads."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class _Model(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")


class PersonalInfo(_Model):
    id: str
    age: int | None = None
    weight: float | None = None  # kg
    height: float | None = None  # m
    biological_sex: str | None = None
    email: str | None = None


class HeartRateSample(_Model):
    bpm: int
    source: str
    timestamp: datetime  # carries the offset Oura reports


class Page(_Model):
    """One page of a list endpoint; follow `next_token` for the rest."""

    data: list[dict[str, Any]]
    next_token: str | None = None
