import asyncio
import os
from dataclasses import dataclass
from datetime import UTC, datetime

import pytest

from timeline_api.adapters import PacsAdapter, VitalsAdapter
from timeline_api.config import Settings
from timeline_api.domain import ImagingEvent, VitalsEvent
from timeline_api.resources import close_resources, create_resources

LIVE_TESTS_ENABLED = os.getenv("TIMELINE_RUN_LIVE_TESTS") == "1"
pytestmark = pytest.mark.skipif(
    not LIVE_TESTS_ENABLED,
    reason="set TIMELINE_RUN_LIVE_TESTS=1 to test seeded source services",
)


def utc_datetime(day: int, hour: int, minute: int) -> datetime:
    return datetime(2024, 1, day, hour, minute, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class LiveAdapterResults:
    pacs_counts: dict[str, int]
    vitals_counts: dict[str, int]
    first_imaging: ImagingEvent
    first_vital: VitalsEvent
    imaging_ids_are_stable: bool


async def fetch_live_adapter_results() -> LiveAdapterResults:
    settings = Settings()
    resources = await create_resources(settings)
    pacs = PacsAdapter(
        resources.mongo_client,
        settings.mongo_database,
        settings.pacs_timeout_seconds,
    )
    vitals = VitalsAdapter(
        resources.http_client,
        settings.vitals_timeout_seconds,
    )
    try:
        pacs_cases = {
            "no_bounds": await pacs.fetch_imaging_events(1, None, None),
            "only_from": await pacs.fetch_imaging_events(
                1,
                utc_datetime(16, 10, 0),
                None,
            ),
            "only_to": await pacs.fetch_imaging_events(
                1,
                None,
                utc_datetime(15, 10, 0),
            ),
            "both_bounds": await pacs.fetch_imaging_events(
                1,
                utc_datetime(15, 10, 0),
                utc_datetime(15, 12, 0),
            ),
            "exact_boundary": await pacs.fetch_imaging_events(
                1,
                utc_datetime(15, 10, 0),
                utc_datetime(15, 10, 0),
            ),
            "unknown_patient": await pacs.fetch_imaging_events(999, None, None),
        }
        repeated_imaging = await pacs.fetch_imaging_events(1, None, None)
        vitals_cases = {
            "no_bounds": await vitals.fetch_vitals_events(1, None, None),
            "only_from": await vitals.fetch_vitals_events(
                1,
                utc_datetime(16, 13, 0),
                None,
            ),
            "only_to": await vitals.fetch_vitals_events(
                1,
                None,
                utc_datetime(15, 10, 0),
            ),
            "both_bounds": await vitals.fetch_vitals_events(
                1,
                utc_datetime(15, 10, 0),
                utc_datetime(15, 12, 0),
            ),
            "exact_boundary": await vitals.fetch_vitals_events(
                1,
                utc_datetime(15, 10, 0),
                utc_datetime(15, 10, 0),
            ),
            "unknown_patient": await vitals.fetch_vitals_events(999, None, None),
        }
        return LiveAdapterResults(
            pacs_counts={name: len(events) for name, events in pacs_cases.items()},
            vitals_counts={name: len(events) for name, events in vitals_cases.items()},
            first_imaging=pacs_cases["no_bounds"][0],
            first_vital=vitals_cases["no_bounds"][0],
            imaging_ids_are_stable=tuple(event.id for event in pacs_cases["no_bounds"])
            == tuple(event.id for event in repeated_imaging),
        )
    finally:
        await close_resources(resources)


def test_live_source_adapters_match_supplied_seed_contracts() -> None:
    results = asyncio.run(fetch_live_adapter_results())

    assert results.pacs_counts == {
        "no_bounds": 17,
        "only_from": 7,
        "only_to": 2,
        "both_bounds": 3,
        "exact_boundary": 1,
        "unknown_patient": 0,
    }
    assert results.vitals_counts == {
        "no_bounds": 22,
        "only_from": 5,
        "only_to": 2,
        "both_bounds": 4,
        "exact_boundary": 1,
        "unknown_patient": 0,
    }
    assert results.imaging_ids_are_stable
    assert results.first_imaging.id.startswith("pacs:imaging:")
    assert results.first_imaging.timestamp == utc_datetime(15, 9, 59)
    assert results.first_imaging.data.modality == "Ultrasound"
    assert results.first_vital.id == "vitals:vitals:1:2024-01-15T09:59:00Z"
    assert results.first_vital.timestamp == utc_datetime(15, 9, 59)
    assert results.first_vital.data.bpm == 65
