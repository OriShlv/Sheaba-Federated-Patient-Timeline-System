from collections.abc import Mapping
from datetime import UTC, datetime

import asyncpg

from timeline_api.domain import (
    EmergencyRoomData,
    EmergencyRoomEvent,
    EventSource,
    EventType,
    ParentEvent,
    SurgeryData,
    SurgeryEvent,
    build_event_id,
)

SURGERIES_QUERY = """
SELECT id, patient_id, surgeon_name, procedure, start_time, end_time
FROM surgeries
WHERE patient_id = $1
  AND ($2::timestamp IS NULL OR end_time >= $2::timestamp)
  AND ($3::timestamp IS NULL OR start_time <= $3::timestamp)
ORDER BY start_time DESC, id ASC
"""

EMERGENCY_ROOMS_QUERY = """
SELECT id, patient_id, attending_physician, chief_complaint, start_time, end_time
FROM emergency_rooms
WHERE patient_id = $1
  AND ($2::timestamp IS NULL OR end_time >= $2::timestamp)
  AND ($3::timestamp IS NULL OR start_time <= $3::timestamp)
ORDER BY start_time DESC, id ASC
"""


def normalize_registry_datetime(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def to_registry_query_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.astimezone(UTC).replace(tzinfo=None)


def read_row_value[T](
    row: Mapping[str, object],
    column: str,
    expected_type: type[T],
) -> T:
    value = row[column]
    if not isinstance(value, expected_type):
        raise TypeError(f"Registry column {column!r} must be {expected_type.__name__}")
    return value


def map_surgery(row: Mapping[str, object]) -> SurgeryEvent:
    source_id = read_row_value(row, "id", int)
    start = normalize_registry_datetime(read_row_value(row, "start_time", datetime))
    end = normalize_registry_datetime(read_row_value(row, "end_time", datetime))
    return SurgeryEvent(
        id=build_event_id(EventSource.REGISTRY, EventType.SURGERY, source_id),
        type=EventType.SURGERY,
        source=EventSource.REGISTRY,
        timestamp=start,
        patient_id=read_row_value(row, "patient_id", int),
        start=start,
        end=end,
        data=SurgeryData(
            surgeon_name=read_row_value(row, "surgeon_name", str),
            procedure=read_row_value(row, "procedure", str),
        ),
    )


def map_emergency_room(row: Mapping[str, object]) -> EmergencyRoomEvent:
    source_id = read_row_value(row, "id", int)
    start = normalize_registry_datetime(read_row_value(row, "start_time", datetime))
    end = normalize_registry_datetime(read_row_value(row, "end_time", datetime))
    return EmergencyRoomEvent(
        id=build_event_id(EventSource.REGISTRY, EventType.EMERGENCY_ROOM, source_id),
        type=EventType.EMERGENCY_ROOM,
        source=EventSource.REGISTRY,
        timestamp=start,
        patient_id=read_row_value(row, "patient_id", int),
        start=start,
        end=end,
        data=EmergencyRoomData(
            attending_physician=read_row_value(row, "attending_physician", str),
            chief_complaint=read_row_value(row, "chief_complaint", str),
        ),
    )


class RegistryAdapter:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def fetch_parent_events(
        self,
        patient_id: int,
        from_: datetime | None,
        to: datetime | None,
    ) -> tuple[ParentEvent, ...]:
        query_from = to_registry_query_datetime(from_)
        query_to = to_registry_query_datetime(to)
        surgery_rows = await self._pool.fetch(
            SURGERIES_QUERY,
            patient_id,
            query_from,
            query_to,
        )
        emergency_room_rows = await self._pool.fetch(
            EMERGENCY_ROOMS_QUERY,
            patient_id,
            query_from,
            query_to,
        )
        events: tuple[ParentEvent, ...] = (
            *(map_surgery(row) for row in surgery_rows),
            *(map_emergency_room(row) for row in emergency_room_rows),
        )
        return tuple(sorted(events, key=lambda event: (-event.start.timestamp(), event.id)))
