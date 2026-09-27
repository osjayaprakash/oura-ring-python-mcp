"""Oura API v2 day-keyed document collections."""

from __future__ import annotations

from enum import StrEnum


class Collection(StrEnum):
    """A `/v2/usercollection/{name}` endpoint queried with start_date/end_date."""

    DAILY_SLEEP = "daily_sleep"
    SLEEP = "sleep"
    DAILY_READINESS = "daily_readiness"
    DAILY_ACTIVITY = "daily_activity"
    DAILY_STRESS = "daily_stress"
    DAILY_SPO2 = "daily_spo2"
    DAILY_RESILIENCE = "daily_resilience"
    WORKOUT = "workout"
    SESSION = "session"

    @property
    def path(self) -> str:
        return f"/v2/usercollection/{self.value}"
