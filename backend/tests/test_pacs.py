import asyncio
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta, timezone
from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from bson import ObjectId
from pymongo import AsyncMongoClient
from pymongo.errors import ServerSelectionTimeoutError

from timeline_api.adapters.pacs import (
    IMAGING_PROJECTION,
    PacsAdapter,
    PacsDocumentValidationError,
)
from timeline_api.domain import EventSource, EventType, ImagingEvent

SOURCE_ID = ObjectId("65a520800000000000000001")
UTC_TIMESTAMP = datetime(2024, 1, 15, 10, tzinfo=UTC)
IMAGING_DOCUMENT: dict[str, object] = {
    "_id": SOURCE_ID,
    "patientId": 7,
    "modality": "CT",
    "timestamp": UTC_TIMESTAMP,
    "radiologistNote": "No abnormalities",
}


def create_client(
    documents: list[dict[str, object]],
) -> tuple[AsyncMongoClient[dict[str, object]], MagicMock, AsyncMock]:
    cursor = MagicMock()
    cursor.to_list = AsyncMock(return_value=documents)
    collection = MagicMock()
    collection.find.return_value = cursor
    database = MagicMock()
    database.__getitem__.return_value = collection
    client = MagicMock()
    client.__getitem__.return_value = database
    return cast(AsyncMongoClient[dict[str, object]], client), collection, cursor.to_list


@pytest.mark.parametrize(
    ("from_", "to", "expected_query"),
    [
        (None, None, {"patientId": 7}),
        (
            datetime(2024, 1, 15, 12, tzinfo=timezone(timedelta(hours=2))),
            None,
            {"patientId": 7, "timestamp": {"$gte": UTC_TIMESTAMP}},
        ),
        (
            None,
            datetime(2024, 1, 15, 8, tzinfo=timezone(timedelta(hours=-2))),
            {"patientId": 7, "timestamp": {"$lte": UTC_TIMESTAMP}},
        ),
        (
            UTC_TIMESTAMP,
            UTC_TIMESTAMP,
            {
                "patientId": 7,
                "timestamp": {
                    "$gte": UTC_TIMESTAMP,
                    "$lte": UTC_TIMESTAMP,
                },
            },
        ),
    ],
)
def test_pacs_builds_patient_and_inclusive_point_query(
    from_: datetime | None,
    to: datetime | None,
    expected_query: dict[str, object],
) -> None:
    client, collection, _to_list = create_client([])
    adapter = PacsAdapter(client, "pacs", 2.5)

    with patch(
        "timeline_api.adapters.pacs.pymongo.timeout",
        return_value=nullcontext(),
    ) as timeout:
        events = asyncio.run(adapter.fetch_imaging_events(7, from_, to))

    assert events == ()
    collection.find.assert_called_once_with(expected_query, IMAGING_PROJECTION)
    timeout.assert_called_once_with(2.5)


def test_pacs_query_excludes_other_patients_and_out_of_range_points() -> None:
    client, collection, _to_list = create_client([])
    adapter = PacsAdapter(client, "pacs", 5.0)
    from_ = datetime(2024, 1, 15, 10, tzinfo=UTC)
    to = datetime(2024, 1, 15, 12, tzinfo=UTC)

    with patch("timeline_api.adapters.pacs.pymongo.timeout", return_value=nullcontext()):
        asyncio.run(adapter.fetch_imaging_events(9, from_, to))

    query = collection.find.call_args.args[0]
    assert query == {
        "patientId": 9,
        "timestamp": {"$gte": from_, "$lte": to},
    }
    assert "$gt" not in query["timestamp"]
    assert "$lt" not in query["timestamp"]


def test_pacs_normalizes_imaging_document_and_stable_id() -> None:
    client, _collection, _to_list = create_client([IMAGING_DOCUMENT])
    adapter = PacsAdapter(client, "pacs", 5.0)

    with patch("timeline_api.adapters.pacs.pymongo.timeout", return_value=nullcontext()):
        events = asyncio.run(adapter.fetch_imaging_events(7, None, None))

    assert len(events) == 1
    event = events[0]
    assert isinstance(event, ImagingEvent)
    assert event.id == f"pacs:imaging:{SOURCE_ID}"
    assert event.type is EventType.IMAGING
    assert event.source is EventSource.PACS
    assert event.patient_id == 7
    assert event.timestamp == UTC_TIMESTAMP
    assert event.data.modality == "CT"
    assert event.data.radiologist_note == "No abnormalities"
    assert set(event.model_dump()) == {
        "id",
        "type",
        "source",
        "timestamp",
        "patient_id",
        "data",
    }


@pytest.mark.parametrize(
    ("source_timestamp", "expected"),
    [
        (datetime(2024, 1, 15, 10), UTC_TIMESTAMP),
        (
            datetime(2024, 1, 15, 12, tzinfo=timezone(timedelta(hours=2))),
            UTC_TIMESTAMP,
        ),
    ],
)
def test_pacs_normalizes_naive_and_aware_timestamps_to_utc(
    source_timestamp: datetime,
    expected: datetime,
) -> None:
    document = {**IMAGING_DOCUMENT, "timestamp": source_timestamp}
    client, _collection, _to_list = create_client([document])
    adapter = PacsAdapter(client, "pacs", 5.0)

    with patch("timeline_api.adapters.pacs.pymongo.timeout", return_value=nullcontext()):
        event = asyncio.run(adapter.fetch_imaging_events(7, None, None))[0]

    assert event.timestamp == expected
    assert event.timestamp.tzinfo is UTC


@pytest.mark.parametrize(
    "invalid_document",
    [
        {key: value for key, value in IMAGING_DOCUMENT.items() if key != "radiologistNote"},
        {**IMAGING_DOCUMENT, "patientId": "7"},
        {**IMAGING_DOCUMENT, "unexpected": "raw source field"},
    ],
)
def test_pacs_rejects_malformed_source_documents(
    invalid_document: dict[str, object],
) -> None:
    client, _collection, _to_list = create_client([invalid_document])
    adapter = PacsAdapter(client, "pacs", 5.0)

    with (
        patch("timeline_api.adapters.pacs.pymongo.timeout", return_value=nullcontext()),
        pytest.raises(PacsDocumentValidationError) as error,
    ):
        asyncio.run(adapter.fetch_imaging_events(7, None, None))

    assert "No abnormalities" not in str(error.value)
    assert "raw source field" not in str(error.value)


def test_pacs_preserves_named_mongo_operational_failure() -> None:
    client, _collection, to_list = create_client([])
    failure = ServerSelectionTimeoutError("upstream unavailable")
    to_list.side_effect = failure
    adapter = PacsAdapter(client, "pacs", 5.0)

    with (
        patch("timeline_api.adapters.pacs.pymongo.timeout", return_value=nullcontext()),
        pytest.raises(ServerSelectionTimeoutError) as error,
    ):
        asyncio.run(adapter.fetch_imaging_events(7, None, None))

    assert error.value is failure
