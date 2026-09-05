import asyncio
import os
from collections import Counter
from datetime import UTC, datetime

import asyncpg
import pytest
from fastapi.testclient import TestClient

from timeline_api.adapters import RegistryAdapter
from timeline_api.config import Settings
from timeline_api.main import create_app

LIVE_TESTS_ENABLED = os.getenv("TIMELINE_RUN_LIVE_TESTS") == "1"
pytestmark = pytest.mark.skipif(
    not LIVE_TESTS_ENABLED,
    reason="set TIMELINE_RUN_LIVE_TESTS=1 to test seeded PostgreSQL",
)


def utc_datetime(day: int, hour: int, minute: int) -> datetime:
    return datetime(2024, 1, day, hour, minute, tzinfo=UTC)


async def fetch_live_event_counts() -> dict[str, int]:
    settings = Settings()
    pool = await asyncpg.create_pool(
        dsn=str(settings.postgres_dsn),
        min_size=0,
        max_size=1,
    )
    adapter = RegistryAdapter(pool)
    try:
        cases = {
            "no_bounds": await adapter.fetch_parent_events(1, None, None),
            "only_from": await adapter.fetch_parent_events(1, utc_datetime(16, 10, 0), None),
            "only_to": await adapter.fetch_parent_events(1, None, utc_datetime(16, 11, 0)),
            "exact_start": await adapter.fetch_parent_events(
                1,
                utc_datetime(15, 10, 0),
                utc_datetime(15, 10, 0),
            ),
            "exact_end": await adapter.fetch_parent_events(
                1,
                utc_datetime(15, 12, 0),
                utc_datetime(15, 12, 0),
            ),
            "non_overlapping": await adapter.fetch_parent_events(
                1,
                utc_datetime(15, 12, 1),
                utc_datetime(15, 13, 59),
            ),
            "unknown_patient": await adapter.fetch_parent_events(999, None, None),
        }
        return {name: len(events) for name, events in cases.items()}
    finally:
        await pool.close()


def test_live_registry_patient_and_interval_overlap_filters() -> None:
    assert asyncio.run(fetch_live_event_counts()) == {
        "no_bounds": 5,
        "only_from": 3,
        "only_to": 4,
        "exact_start": 1,
        "exact_end": 1,
        "non_overlapping": 0,
        "unknown_patient": 0,
    }


def test_live_endpoint_returns_seeded_registry_parents() -> None:
    application = create_app(Settings())

    with TestClient(application) as client:
        response = client.get("/api/timeline", params={"patientId": "1"})

    assert response.status_code == 200
    body = response.json()
    assert Counter(parent["type"] for parent in body["parents"]) == {
        "surgery": 3,
        "emergency_room": 2,
    }
    assert body["standalone"] == []
    assert body["partial"] is False
