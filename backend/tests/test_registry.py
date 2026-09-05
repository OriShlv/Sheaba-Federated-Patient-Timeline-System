import asyncio
from datetime import UTC, datetime, timedelta, timezone
from typing import cast
from unittest.mock import AsyncMock, call

import asyncpg
import pytest

from timeline_api.adapters.registry import (
    EMERGENCY_ROOMS_QUERY,
    SURGERIES_QUERY,
    RegistryAdapter,
)
from timeline_api.domain import EmergencyRoomEvent, EventSource, EventType, SurgeryEvent

NAIVE_START = datetime(2024, 1, 15, 10)
NAIVE_END = datetime(2024, 1, 15, 12)

SURGERY_ROW: dict[str, object] = {
    "id": 11,
    "patient_id": 7,
    "surgeon_name": "Dr. Williams",
    "procedure": "Appendectomy",
    "start_time": NAIVE_START,
    "end_time": NAIVE_END,
}

EMERGENCY_ROOM_ROW: dict[str, object] = {
    "id": 22,
    "patient_id": 7,
    "attending_physician": "Dr. Wilson",
    "chief_complaint": "Chest pain",
    "start_time": datetime(2024, 1, 15, 14),
    "end_time": datetime(2024, 1, 15, 16),
}


def create_pool(
    surgery_rows: list[dict[str, object]],
    emergency_room_rows: list[dict[str, object]],
) -> tuple[asyncpg.Pool, AsyncMock]:
    pool_mock = AsyncMock(spec=asyncpg.Pool)
    pool_mock.fetch.side_effect = [surgery_rows, emergency_room_rows]
    return cast(asyncpg.Pool, pool_mock), pool_mock


def test_registry_normalizes_source_rows_and_stable_ids() -> None:
    pool, pool_mock = create_pool([SURGERY_ROW], [EMERGENCY_ROOM_ROW])
    adapter = RegistryAdapter(pool)

    events = asyncio.run(
        adapter.fetch_parent_events(
            patient_id=7,
            from_=None,
            to=None,
        )
    )

    assert pool_mock.fetch.await_args_list == [
        call(SURGERIES_QUERY, 7, None, None),
        call(EMERGENCY_ROOMS_QUERY, 7, None, None),
    ]
    assert "$1" in SURGERIES_QUERY
    assert "$1" in EMERGENCY_ROOMS_QUERY
    assert "end_time >= $2::timestamp" in SURGERIES_QUERY
    assert "start_time <= $3::timestamp" in SURGERIES_QUERY

    emergency_room, surgery = events
    assert isinstance(surgery, SurgeryEvent)
    assert surgery.id == "registry:surgery:11"
    assert surgery.type is EventType.SURGERY
    assert surgery.source is EventSource.REGISTRY
    assert surgery.data.surgeon_name == "Dr. Williams"
    assert surgery.data.procedure == "Appendectomy"
    assert surgery.timestamp == NAIVE_START.replace(tzinfo=UTC)
    assert surgery.start.tzinfo is UTC
    assert surgery.end.tzinfo is UTC

    assert isinstance(emergency_room, EmergencyRoomEvent)
    assert emergency_room.id == "registry:emergency_room:22"
    assert emergency_room.type is EventType.EMERGENCY_ROOM
    assert emergency_room.source is EventSource.REGISTRY
    assert emergency_room.data.attending_physician == "Dr. Wilson"
    assert emergency_room.data.chief_complaint == "Chest pain"
    assert all(isinstance(event, SurgeryEvent | EmergencyRoomEvent) for event in events)


@pytest.mark.parametrize(
    ("from_", "to", "expected_from", "expected_to"),
    [
        (None, None, None, None),
        (
            datetime(2024, 1, 15, 12, tzinfo=timezone(timedelta(hours=2))),
            None,
            datetime(2024, 1, 15, 10),
            None,
        ),
        (
            None,
            datetime(2024, 1, 15, 12, tzinfo=timezone(timedelta(hours=-2))),
            None,
            datetime(2024, 1, 15, 14),
        ),
        (
            datetime(2024, 1, 15, 10, tzinfo=UTC),
            datetime(2024, 1, 15, 12, tzinfo=UTC),
            datetime(2024, 1, 15, 10),
            datetime(2024, 1, 15, 12),
        ),
    ],
)
def test_registry_passes_optional_utc_bounds_as_naive_query_parameters(
    from_: datetime | None,
    to: datetime | None,
    expected_from: datetime | None,
    expected_to: datetime | None,
) -> None:
    pool, pool_mock = create_pool([], [])
    adapter = RegistryAdapter(pool)

    events = asyncio.run(
        adapter.fetch_parent_events(
            patient_id=7,
            from_=from_,
            to=to,
        )
    )

    assert events == ()
    assert pool_mock.fetch.await_args_list == [
        call(SURGERIES_QUERY, 7, expected_from, expected_to),
        call(EMERGENCY_ROOMS_QUERY, 7, expected_from, expected_to),
    ]
