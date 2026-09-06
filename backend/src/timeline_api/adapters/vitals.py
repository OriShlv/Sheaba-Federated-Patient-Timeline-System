from datetime import UTC, datetime

import httpx
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from timeline_api.domain import (
    EventSource,
    EventType,
    VitalsData,
    VitalsEvent,
    build_event_id,
)


class VitalsResponseValidationError(ValueError):
    """Raised when the Vitals response does not match the supplied source contract."""


class VitalsReading(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    bpm: int = Field(gt=0)
    bp: str = Field(min_length=1)
    timestamp: datetime


VITALS_RESPONSE_ADAPTER = TypeAdapter(list[VitalsReading])


def normalize_vitals_datetime(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def vitals_source_key(patient_id: int, timestamp: datetime) -> str:
    utc_timestamp = normalize_vitals_datetime(timestamp)
    return f"{patient_id}:{utc_timestamp.isoformat().replace('+00:00', 'Z')}"


def parse_vitals_response(response: httpx.Response) -> list[VitalsReading]:
    try:
        return VITALS_RESPONSE_ADAPTER.validate_json(response.content, strict=True)
    except ValidationError:
        raise VitalsResponseValidationError(
            "Vitals response must be a JSON array of valid readings"
        ) from None


def map_vitals_reading(patient_id: int, reading: VitalsReading) -> VitalsEvent:
    timestamp = normalize_vitals_datetime(reading.timestamp)
    return VitalsEvent(
        id=build_event_id(
            EventSource.VITALS,
            EventType.VITALS,
            vitals_source_key(patient_id, timestamp),
        ),
        type=EventType.VITALS,
        source=EventSource.VITALS,
        timestamp=timestamp,
        patient_id=patient_id,
        data=VitalsData(bpm=reading.bpm, bp=reading.bp),
    )


def is_within_point_bounds(
    timestamp: datetime,
    from_: datetime | None,
    to: datetime | None,
) -> bool:
    normalized_from = normalize_vitals_datetime(from_) if from_ is not None else None
    normalized_to = normalize_vitals_datetime(to) if to is not None else None
    return (normalized_from is None or timestamp >= normalized_from) and (
        normalized_to is None or timestamp <= normalized_to
    )


class VitalsAdapter:
    def __init__(
        self,
        client: httpx.AsyncClient,
        timeout_seconds: float,
    ) -> None:
        self._client = client
        self._timeout_seconds = timeout_seconds

    async def fetch_vitals_events(
        self,
        patient_id: int,
        from_: datetime | None,
        to: datetime | None,
    ) -> tuple[VitalsEvent, ...]:
        response = await self._client.get(
            f"/vitals/{patient_id}",
            timeout=self._timeout_seconds,
        )
        response.raise_for_status()
        readings = parse_vitals_response(response)
        events = tuple(map_vitals_reading(patient_id, reading) for reading in readings)
        return tuple(
            event
            for event in sorted(events, key=lambda item: (item.timestamp, item.id))
            if is_within_point_bounds(event.timestamp, from_, to)
        )
