from datetime import UTC, date, datetime, timedelta

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from oura_ring_mcp.service import resolve_date_range, resolve_time_range

TODAY = date(2026, 9, 26)
NOW = datetime(2026, 9, 26, 12, 0, tzinfo=UTC)


@pytest.mark.parametrize("start, end", [(None, None), ("", ""), ("  ", " ")])
def test_default_is_seven_days_ending_today(start, end):
    days = resolve_date_range(start, end, today=TODAY)
    assert (days.start, days.end) == (date(2026, 9, 20), TODAY)


def test_end_only_counts_back_seven_days():
    days = resolve_date_range(None, "2026-01-07", today=TODAY)
    assert (days.start, days.end) == (date(2026, 1, 1), date(2026, 1, 7))


def test_start_only_runs_to_today():
    days = resolve_date_range("2026-09-01", None, today=TODAY)
    assert (days.start, days.end) == (date(2026, 9, 1), TODAY)


def test_single_day():
    days = resolve_date_range("2026-09-25", "2026-09-25", today=TODAY)
    assert days.start == days.end == date(2026, 9, 25)


def test_bad_date_names_the_argument():
    with pytest.raises(ToolError, match="start_date 'last week' is not a date"):
        resolve_date_range("last week", None, today=TODAY)


def test_reversed_range():
    with pytest.raises(ToolError, match="is after end_date"):
        resolve_date_range("2026-09-26", "2026-09-01", today=TODAY)


def test_ninety_days_ok_ninety_one_rejected():
    resolve_date_range("2026-06-29", "2026-09-26", today=TODAY)
    with pytest.raises(ToolError, match="longer than 90 days"):
        resolve_date_range("2026-06-28", "2026-09-26", today=TODAY)


def test_time_default_is_last_24_hours():
    window = resolve_time_range(None, None, now=NOW)
    assert (window.start, window.end) == (NOW - timedelta(hours=24), NOW)


def test_time_keeps_explicit_offset():
    window = resolve_time_range("2026-09-26T08:00:00+02:00", "2026-09-26T09:00:00+02:00", now=NOW)
    assert window.start.utcoffset() == timedelta(hours=2)


def test_naive_time_is_local_and_aware():
    window = resolve_time_range("2026-09-26T08:00:00", "2026-09-26T09:00:00", now=NOW)
    assert window.start.tzinfo is not None
    assert window.end - window.start == timedelta(hours=1)


def test_date_only_is_accepted_as_midnight():
    window = resolve_time_range("2026-09-25", "2026-09-26", now=NOW)
    assert window.end - window.start == timedelta(days=1)


def test_bad_time():
    with pytest.raises(ToolError, match="end_datetime 'noon' is not a date-time"):
        resolve_time_range(None, "noon", now=NOW)


def test_time_start_must_precede_end():
    with pytest.raises(ToolError, match="is not before"):
        resolve_time_range("2026-09-26T09:00:00+00:00", "2026-09-26T09:00:00+00:00", now=NOW)


def test_time_window_capped_at_seven_days():
    tz = UTC
    end = datetime(2026, 9, 26, tzinfo=tz)
    resolve_time_range((end - timedelta(days=7)).isoformat(), end.isoformat(), now=NOW)
    with pytest.raises(ToolError, match="longer than 7 days"):
        resolve_time_range(
            (end - timedelta(days=7, seconds=1)).isoformat(), end.isoformat(), now=NOW
        )
