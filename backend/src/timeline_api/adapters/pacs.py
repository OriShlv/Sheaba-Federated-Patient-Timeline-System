from datetime import UTC, datetime

import pymongo
from bson import ObjectId
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from pymongo import AsyncMongoClient
from pymongo.asynchronous.collection import AsyncCollection

from timeline_api.domain import (
    EventSource,
    EventType,
    ImagingData,
    ImagingEvent,
    build_event_id,
)

IMAGING_PROJECTION: dict[str, int] = {
    "_id": 1,
    "patientId": 1,
    "modality": 1,
    "timestamp": 1,
    "radiologistNote": 1,
}


class PacsDocumentValidationError(ValueError):
    """Raised when a PACS document does not match the supplied source contract."""


class PacsImagingDocument(BaseModel):
    model_config = ConfigDict(
        arbitrary_types_allowed=True,
        extra="forbid",
        strict=True,
    )

    source_id: ObjectId = Field(alias="_id")
    patient_id: int = Field(alias="patientId", gt=0)
    modality: str = Field(min_length=1)
    timestamp: datetime
    radiologist_note: str = Field(alias="radiologistNote", min_length=1)


def normalize_pacs_datetime(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def build_imaging_query(
    patient_id: int,
    from_: datetime | None,
    to: datetime | None,
) -> dict[str, object]:
    query: dict[str, object] = {"patientId": patient_id}
    timestamp_filter: dict[str, datetime] = {}
    if from_ is not None:
        timestamp_filter["$gte"] = normalize_pacs_datetime(from_)
    if to is not None:
        timestamp_filter["$lte"] = normalize_pacs_datetime(to)
    if timestamp_filter:
        query["timestamp"] = timestamp_filter
    return query


def map_imaging_document(document: dict[str, object]) -> ImagingEvent:
    try:
        source = PacsImagingDocument.model_validate(document)
    except ValidationError:
        raise PacsDocumentValidationError(
            "PACS imaging document is missing or has invalid required fields"
        ) from None

    timestamp = normalize_pacs_datetime(source.timestamp)
    return ImagingEvent(
        id=build_event_id(EventSource.PACS, EventType.IMAGING, str(source.source_id)),
        type=EventType.IMAGING,
        source=EventSource.PACS,
        timestamp=timestamp,
        patient_id=source.patient_id,
        data=ImagingData(
            modality=source.modality,
            radiologist_note=source.radiologist_note,
        ),
    )


class PacsAdapter:
    def __init__(
        self,
        client: AsyncMongoClient[dict[str, object]],
        database_name: str,
        timeout_seconds: float,
    ) -> None:
        self._client = client
        self._database_name = database_name
        self._timeout_seconds = timeout_seconds

    async def fetch_imaging_events(
        self,
        patient_id: int,
        from_: datetime | None,
        to: datetime | None,
    ) -> tuple[ImagingEvent, ...]:
        collection: AsyncCollection[dict[str, object]] = self._client[self._database_name][
            "imaging"
        ]
        query = build_imaging_query(patient_id, from_, to)
        with pymongo.timeout(self._timeout_seconds):
            documents = await collection.find(query, IMAGING_PROJECTION).to_list()

        events = tuple(map_imaging_document(document) for document in documents)
        return tuple(sorted(events, key=lambda event: (event.timestamp, event.id)))
