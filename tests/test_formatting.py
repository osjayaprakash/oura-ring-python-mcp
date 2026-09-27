import json
from datetime import UTC, date, datetime

from oura_ring_mcp.formatting import (
    documents_response,
    heart_rate_response,
    personal_info_to_dict,
)
from oura_ring_mcp.service import DateRange, TimeRange
from tests.fakes import ME, sample

DAYS = DateRange(date(2026, 9, 20), date(2026, 9, 26))
WINDOW = TimeRange(datetime(2026, 9, 26, tzinfo=UTC), datetime(2026, 9, 26, 12, tzinfo=UTC))


def test_personal_info():
    assert personal_info_to_dict(ME) == {
        "id": "user-0001",
        "age": 34,
        "weight": 70.5,
        "height": 1.78,
        "biological_sex": "male",
        "email": None,
    }


def test_documents_echo_range_and_sort_by_day_then_start():
    nap = {"day": "2026-09-25", "bedtime_start": "2026-09-25T14:00:00+02:00", "type": "rest"}
    night = {"day": "2026-09-25", "bedtime_start": "2026-09-24T23:00:00+02:00"}
    earlier = {"day": "2026-09-21"}
    result = documents_response(DAYS, [nap, night, earlier])
    assert (result["start_date"], result["end_date"], result["count"]) == (
        "2026-09-20",
        "2026-09-26",
        3,
    )
    assert result["items"] == [earlier, night, nap]


def test_documents_drop_interval_series_but_keep_summaries():
    sleep = {
        "day": "2026-09-25",
        "average_heart_rate": 54.5,
        "heart_rate": {"interval": 300, "items": [60, 58]},
        "hrv": {"interval": 300, "items": [50, 62]},
        "sleep_phase_5_min": "4422",
        "movement_30_sec": "1121",
    }
    activity = {"day": "2026-09-25", "steps": 9000, "class_5_min": "0012", "met": {"items": []}}
    session = {
        "day": "2026-09-25",
        "mood": "good",
        "contributors": {"items": "not a series"},
        "heart_rate_variability": {"interval": 5, "items": [40, None]},
        "motion_count": {"interval": 5, "items": [0, 1]},
        "app_sleep_phase_5_min": "4422",
    }
    items = documents_response(DAYS, [sleep, activity, session])["items"]
    assert items[0] == {"day": "2026-09-25", "average_heart_rate": 54.5}
    assert items[1] == {"day": "2026-09-25", "steps": 9000}
    assert items[2] == {
        "day": "2026-09-25",
        "mood": "good",
        "contributors": {"items": "not a series"},
    }


def test_documents_empty():
    assert documents_response(DAYS, [])["items"] == []


def test_heart_rate_sorted_with_summary():
    result = heart_rate_response(
        WINDOW,
        [sample("2026-09-26T08:05:00+00:00", 62), sample("2026-09-26T08:00:00+00:00", 55, "rest")],
    )
    assert result["count"] == 2
    assert (result["min_bpm"], result["max_bpm"], result["avg_bpm"]) == (55, 62, 58.5)
    assert result["samples"][0] == {
        "timestamp": "2026-09-26T08:00:00+00:00",
        "bpm": 55,
        "source": "rest",
    }
    assert result["start_datetime"] == "2026-09-26T00:00:00+00:00"


def test_heart_rate_empty_window():
    result = heart_rate_response(WINDOW, [])
    assert result["count"] == 0
    assert result["min_bpm"] is None and result["avg_bpm"] is None


def test_responses_are_json_serialisable():
    json.dumps(heart_rate_response(WINDOW, [sample("2026-09-26T08:00:00+00:00", 55)]))
    json.dumps(documents_response(DAYS, [{"day": "2026-09-25", "score": 80}]))
    json.dumps(personal_info_to_dict(ME))
