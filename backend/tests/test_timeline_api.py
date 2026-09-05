from datetime import UTC, datetime

import asyncpg
import pytest
from fastapi.testclient import TestClient

from timeline_api.adapters import RegistryAdapter
from timeline_api.api.routes import get_timeline_service
from timeline_api.config import Settings
from timeline_api.domain import (
    EventSource,
    EventType,
    ParentEvent,
    SurgeryData,
    SurgeryEvent,
)
from timeline_api.main import create_app
from timeline_api.services import TimelineQuery, TimelineService

START = datetime(2024, 1, 15, 10, tzinfo=UTC)
END = datetime(2024, 1, 15, 12, tzinfo=UTC)
SURGERY = SurgeryEvent(
    id="registry:surgery:1",
    type=EventType.SURGERY,
    source=EventSource.REGISTRY,
    timestamp=START,
    patient_id=1,
    start=START,
    end=END,
    data=SurgeryData(
        surgeon_name="Dr. Williams",
        procedure="Appendectomy",
    ),
)


class StubRegistryAdapter(RegistryAdapter):
    def __init__(self, events: tuple[ParentEvent, ...]) -> None:
        self.events = events
        self.received_queries: list[TimelineQuery] = []

    async def fetch_parent_events(
        self,
        patient_id: int,
        from_: datetime | None,
        to: datetime | None,
    ) -> tuple[ParentEvent, ...]:
        self.received_queries.append(
            TimelineQuery(
                patient_id=patient_id,
                from_=from_,
                to=to,
            )
        )
        return self.events


class FailingRegistryAdapter(RegistryAdapter):
    def __init__(self) -> None:
        pass

    async def fetch_parent_events(
        self,
        patient_id: int,
        from_: datetime | None,
        to: datetime | None,
    ) -> tuple[ParentEvent, ...]:
        raise asyncpg.PostgresError(f"database failure for patient {patient_id}: password=private")


def create_test_client(
    registry_adapter: RegistryAdapter,
) -> tuple[TestClient, TimelineService]:
    application = create_app(Settings())
    service = TimelineService(registry_adapter)

    def override_timeline_service() -> TimelineService:
        return service

    application.dependency_overrides[get_timeline_service] = override_timeline_service
    return TestClient(application, raise_server_exceptions=False), service


def test_registry_data_reaches_http_response_through_timeline_service() -> None:
    registry_adapter = StubRegistryAdapter((SURGERY,))
    client, _service = create_test_client(registry_adapter)

    with client:
        response = client.get(
            "/api/timeline",
            params={
                "patientId": "1",
                "from": "2024-01-15T12:00:00+02:00",
                "to": "2024-01-15T12:00:00Z",
            },
            headers={"X-User-Role": "doctor"},
        )

    assert response.status_code == 200
    assert registry_adapter.received_queries == [
        TimelineQuery(
            patient_id=1,
            from_=START,
            to=datetime(2024, 1, 15, 12, tzinfo=UTC),
        )
    ]
    assert response.json() == {
        "parents": [
            {
                "id": "registry:surgery:1",
                "type": "surgery",
                "source": "registry",
                "timestamp": "2024-01-15T10:00:00Z",
                "patientId": 1,
                "data": {
                    "surgeonName": "Dr. Williams",
                    "procedure": "Appendectomy",
                },
                "start": "2024-01-15T10:00:00Z",
                "end": "2024-01-15T12:00:00Z",
                "children": [],
            }
        ],
        "standalone": [],
        "partial": False,
    }


@pytest.mark.parametrize(
    "params",
    [
        {},
        {"patientId": "0"},
        {"patientId": "not-an-integer"},
        {"patientId": "1", "from": "not-a-date"},
        {
            "patientId": "1",
            "from": "2024-01-16T00:00:00Z",
            "to": "2024-01-15T00:00:00Z",
        },
    ],
)
def test_invalid_core_query_input_returns_400(params: dict[str, str]) -> None:
    client, _service = create_test_client(StubRegistryAdapter(()))

    with client:
        response = client.get("/api/timeline", params=params)

    assert response.status_code == 400
    assert "detail" in response.json()


def test_database_error_details_are_not_exposed() -> None:
    client, _service = create_test_client(FailingRegistryAdapter())

    with client:
        response = client.get("/api/timeline", params={"patientId": "1"})

    assert response.status_code == 500
    assert response.json() == {"detail": "Internal server error"}
    assert "patient 1" not in response.text
    assert "password" not in response.text
