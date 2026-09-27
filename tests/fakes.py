"""A scriptable stand-in for oura_ring_mcp.core.client.OuraClient."""

from __future__ import annotations

from datetime import date, datetime

from oura_ring_mcp.core import Collection, HeartRateSample, PersonalInfo

ME = PersonalInfo(id="user-0001", age=34, weight=70.5, height=1.78, biological_sex="male")


def sample(timestamp: str, bpm: int, source: str = "awake") -> HeartRateSample:
    return HeartRateSample.model_validate({"timestamp": timestamp, "bpm": bpm, "source": source})


class FakeOuraClient:
    """Records calls; `fail_next[method]` holds exceptions to raise, one per call."""

    def __init__(self, documents: dict[Collection, list[dict]] | None = None):
        self.documents_by_collection = documents or {}
        self.samples = [
            sample("2026-09-26T08:05:00+00:00", 62),
            sample("2026-09-26T08:00:00+00:00", 55, "rest"),
        ]
        self.calls: list[tuple] = []
        self.fail_next: dict[str, list[Exception]] = {}

    def _record(self, method: str, *args: object) -> None:
        self.calls.append((method, *args))
        queue = self.fail_next.get(method)
        if queue:
            raise queue.pop(0)

    async def personal_info(self) -> PersonalInfo:
        self._record("personal_info")
        return ME

    async def documents(self, collection: Collection, start_date: date, end_date: date):
        self._record("documents", collection, start_date, end_date)
        return list(self.documents_by_collection.get(collection, []))

    async def heart_rate(self, start: datetime, end: datetime):
        self._record("heart_rate", start, end)
        return list(self.samples)
