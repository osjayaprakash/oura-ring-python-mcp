from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from oura_ring_mcp.core import Collection, HeartRateSample, PersonalInfo
from oura_ring_mcp.core.models import Page


def test_personal_info_fields_are_optional_except_id():
    info = PersonalInfo.model_validate({"id": "u1", "unknown_field": 1})
    assert info.id == "u1" and info.age is None
    with pytest.raises(ValidationError):
        PersonalInfo.model_validate({"age": 34})


def test_heart_rate_sample_keeps_offset():
    s = HeartRateSample.model_validate(
        {"bpm": 60, "source": "rest", "timestamp": "2026-09-26T08:00:00+00:00"}
    )
    assert s.timestamp == datetime(2026, 9, 26, 8, tzinfo=UTC)


def test_page_next_token_defaults_to_none():
    assert Page.model_validate({"data": []}).next_token is None


def test_collection_paths():
    assert Collection.DAILY_SLEEP.path == "/v2/usercollection/daily_sleep"
    assert Collection.WORKOUT.path == "/v2/usercollection/workout"
    assert len(Collection) == 9
