"""Convert core models and Oura documents into JSON-serialisable dicts for tool results."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from oura_ring_mcp.core import HeartRateSample, PersonalInfo
from oura_ring_mcp.service import DateRange, TimeRange

# Per-interval series (5-minute activity classes, MET, sleep phases, in-sleep heart rate
# and HRV). They dwarf the scores and totals, so they are left out of tool results.
_SERIES_FIELDS = frozenset(
    {"class_5_min", "met", "sleep_phase_5_min", "sleep_phase_30_sec", "movement_30_sec"}
)
_SAMPLE_OBJECTS = frozenset({"heart_rate", "hrv"})

# Within a day, order documents by when they started.
_START_FIELDS = ("bedtime_start", "start_datetime", "timestamp")


def personal_info_to_dict(info: PersonalInfo) -> dict[str, Any]:
    return info.model_dump()


def _compact(document: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in document.items()
        if key not in _SERIES_FIELDS and not (key in _SAMPLE_OBJECTS and isinstance(value, dict))
    }


def _start(document: dict[str, Any]) -> str:
    for field in _START_FIELDS:
        value = document.get(field)
        if isinstance(value, str):
            return value
    return ""


def documents_response(days: DateRange, documents: Iterable[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(documents, key=lambda d: (str(d.get("day", "")), _start(d)))
    return {
        "start_date": days.start.isoformat(),
        "end_date": days.end.isoformat(),
        "count": len(ordered),
        "items": [_compact(d) for d in ordered],
    }


def heart_rate_response(window: TimeRange, samples: Iterable[HeartRateSample]) -> dict[str, Any]:
    ordered = sorted(samples, key=lambda s: s.timestamp)
    bpms = [s.bpm for s in ordered]
    summary = (
        {"min_bpm": min(bpms), "max_bpm": max(bpms), "avg_bpm": round(sum(bpms) / len(bpms), 1)}
        if bpms
        else {"min_bpm": None, "max_bpm": None, "avg_bpm": None}
    )
    return {
        "start_datetime": window.start.isoformat(),
        "end_datetime": window.end.isoformat(),
        "count": len(ordered),
        **summary,
        "samples": [
            {"timestamp": s.timestamp.isoformat(), "bpm": s.bpm, "source": s.source}
            for s in ordered
        ],
    }
