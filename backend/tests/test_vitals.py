import asyncio
from datetime import UTC, datetime
from typing import cast
from unittest.mock import AsyncMock

import httpx
import pytest

from timeline_api.adapters.vitals import VitalsAdapter, VitalsResponseValidationError
from timeline_api.domain import EventSource, EventType, VitalsEvent

UTC_TIMESTAMP = datetime(2024, 1, 15, 10, tzinfo=UTC)
READING: dict[str, object] = {
    "bpm": 72,
    "bp": "120/80",
    "timestamp": "2024-01-15T10:00:00Z",
}


def create_client(
    response: httpx.Response,
) -> tuple[httpx.AsyncClient, AsyncMock]:
    client = AsyncMock(spec=httpx.AsyncClient)
    client.get.return_value = response
    return cast(httpx.AsyncClient, client), client


def create_response(
    payload: object,
    status_code: int,
) -> httpx.Response:
    request = httpx.Request("GET", "http://vitals.test/vitals/7")
    return httpx.Response(status_code, json=payload, request=request)


def test_vitals_constructs_patient_endpoint_and_bounded_request() -> None:
    client, client_mock = create_client(create_response([], 200))
    adapter = VitalsAdapter(client, 3.5)

    events = asyncio.run(adapter.fetch_vitals_events(7, None, None))

    assert events == ()
    client_mock.get.assert_awaited_once_with("/vitals/7", timeout=3.5)


@pytest.mark.parametrize(
    ("from_", "to", "expected_timestamps"),
    [
        (
            None,
            None,
            [datetime(2024, 1, 15, hour, tzinfo=UTC) for hour in (9, 10, 11, 12, 13)],
        ),
        (
            UTC_TIMESTAMP,
            None,
            [datetime(2024, 1, 15, hour, tzinfo=UTC) for hour in (10, 11, 12, 13)],
        ),
        (
            None,
            datetime(2024, 1, 15, 12, tzinfo=UTC),
            [datetime(2024, 1, 15, hour, tzinfo=UTC) for hour in (9, 10, 11, 12)],
        ),
        (
            UTC_TIMESTAMP,
            datetime(2024, 1, 15, 12, tzinfo=UTC),
            [datetime(2024, 1, 15, hour, tzinfo=UTC) for hour in (10, 11, 12)],
        ),
        (
            UTC_TIMESTAMP,
            UTC_TIMESTAMP,
            [UTC_TIMESTAMP],
        ),
    ],
)
def test_vitals_applies_inclusive_point_date_filtering(
    from_: datetime | None,
    to: datetime | None,
    expected_timestamps: list[datetime],
) -> None:
    readings = [
        {
            **READING,
            "timestamp": f"2024-01-15T{hour:02d}:00:00Z",
        }
        for hour in (9, 10, 11, 12, 13)
    ]
    client, _client_mock = create_client(create_response(readings, 200))
    adapter = VitalsAdapter(client, 5.0)

    events = asyncio.run(adapter.fetch_vitals_events(7, from_, to))

    assert [event.timestamp for event in events] == expected_timestamps


def test_vitals_excludes_all_out_of_range_readings() -> None:
    client, _client_mock = create_client(create_response([READING], 200))
    adapter = VitalsAdapter(client, 5.0)

    events = asyncio.run(
        adapter.fetch_vitals_events(
            7,
            datetime(2024, 1, 15, 10, 0, 1, tzinfo=UTC),
            None,
        )
    )

    assert events == ()


def test_vitals_normalizes_reading_and_stable_id_without_raw_response_leakage() -> None:
    client, _client_mock = create_client(create_response([READING], 200))
    adapter = VitalsAdapter(client, 5.0)

    events = asyncio.run(adapter.fetch_vitals_events(7, None, None))

    assert len(events) == 1
    event = events[0]
    assert isinstance(event, VitalsEvent)
    assert event.id == "vitals:vitals:7:2024-01-15T10:00:00Z"
    assert event.type is EventType.VITALS
    assert event.source is EventSource.VITALS
    assert event.patient_id == 7
    assert event.timestamp == UTC_TIMESTAMP
    assert event.data.bpm == 72
    assert event.data.bp == "120/80"
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
        ("2024-01-15T10:00:00", UTC_TIMESTAMP),
        (
            "2024-01-15T12:00:00+02:00",
            UTC_TIMESTAMP,
        ),
    ],
)
def test_vitals_normalizes_naive_and_aware_timestamps_to_utc(
    source_timestamp: str,
    expected: datetime,
) -> None:
    client, _client_mock = create_client(
        create_response([{**READING, "timestamp": source_timestamp}], 200)
    )
    adapter = VitalsAdapter(client, 5.0)

    event = asyncio.run(adapter.fetch_vitals_events(7, None, None))[0]

    assert event.timestamp == expected
    assert event.timestamp.tzinfo is UTC


@pytest.mark.parametrize(
    "payload",
    [
        {"bpm": 72, "bp": "120/80", "timestamp": "2024-01-15T10:00:00Z"},
        [{**READING, "bpm": "72"}],
        [{key: value for key, value in READING.items() if key != "bp"}],
        [{**READING, "unexpected": "raw body value"}],
    ],
)
def test_vitals_rejects_malformed_upstream_structures(payload: object) -> None:
    client, _client_mock = create_client(create_response(payload, 200))
    adapter = VitalsAdapter(client, 5.0)

    with pytest.raises(VitalsResponseValidationError) as error:
        asyncio.run(adapter.fetch_vitals_events(7, None, None))

    assert "raw body value" not in str(error.value)
    assert "120/80" not in str(error.value)


def test_vitals_rejects_malformed_json_without_exposing_body() -> None:
    request = httpx.Request("GET", "http://vitals.test/vitals/7")
    response = httpx.Response(200, content=b"sensitive malformed body", request=request)
    client, _client_mock = create_client(response)
    adapter = VitalsAdapter(client, 5.0)

    with pytest.raises(VitalsResponseValidationError) as error:
        asyncio.run(adapter.fetch_vitals_events(7, None, None))

    assert "sensitive malformed body" not in str(error.value)


def test_vitals_preserves_named_timeout_failure() -> None:
    client_mock = AsyncMock(spec=httpx.AsyncClient)
    request = httpx.Request("GET", "http://vitals.test/vitals/7")
    failure = httpx.ReadTimeout("upstream timeout", request=request)
    client_mock.get.side_effect = failure
    adapter = VitalsAdapter(cast(httpx.AsyncClient, client_mock), 5.0)

    with pytest.raises(httpx.ReadTimeout) as error:
        asyncio.run(adapter.fetch_vitals_events(7, None, None))

    assert error.value is failure


def test_vitals_preserves_named_http_status_failure() -> None:
    response = create_response({"internal": "raw body"}, 503)
    client, _client_mock = create_client(response)
    adapter = VitalsAdapter(client, 5.0)

    with pytest.raises(httpx.HTTPStatusError) as error:
        asyncio.run(adapter.fetch_vitals_events(7, None, None))

    assert error.value.response.status_code == 503
    assert "raw body" not in str(error.value)
