from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from timeline_api.api.routes import get_timeline_service
from timeline_api.config import Settings
from timeline_api.domain import (
    EventSource,
    EventType,
    SurgeryData,
    SurgeryEvent,
    VitalsData,
    VitalsEvent,
)
from timeline_api.main import create_app
from timeline_api.services import TimelineQuery, TimelineResult, TimelineService, UserRole
from timeline_api.services.grouping import GroupedParent

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
VITALS = VitalsEvent(
    id="vitals:vitals:1",
    type=EventType.VITALS,
    source=EventSource.VITALS,
    timestamp=datetime(2024, 1, 15, 10, 30, tzinfo=UTC),
    patient_id=1,
    data=VitalsData(bpm=72, bp="120/80"),
)
COMPLETE_RESULT = TimelineResult(
    parents=(GroupedParent(parent=SURGERY, children=(VITALS,)),),
    standalone=(),
    partial=False,
    unavailable_sources=(),
)
EMPTY_RESULT = TimelineResult(
    parents=(),
    standalone=(),
    partial=False,
    unavailable_sources=(),
)


class StubTimelineService(TimelineService):
    def __init__(self, result: TimelineResult) -> None:
        self.result = result
        self.received_queries: list[TimelineQuery] = []

    async def get_timeline(self, query: TimelineQuery) -> TimelineResult:
        self.received_queries.append(query)
        return self.result


class FailingTimelineService(TimelineService):
    def __init__(self, error: Exception) -> None:
        self.error = error

    async def get_timeline(self, query: TimelineQuery) -> TimelineResult:
        raise self.error


def create_test_client(service: TimelineService) -> TestClient:
    application = create_app(Settings())

    def override_timeline_service() -> TimelineService:
        return service

    application.dependency_overrides[get_timeline_service] = override_timeline_service
    return TestClient(application, raise_server_exceptions=False)


@pytest.mark.parametrize("role", list(UserRole))
def test_valid_role_request_reaches_service(role: UserRole) -> None:
    service = StubTimelineService(EMPTY_RESULT)
    client = create_test_client(service)

    with client:
        response = client.get(
            "/api/timeline",
            params={"patientId": "1"},
            headers={"X-User-Role": role.value},
        )

    assert response.status_code == 200
    assert service.received_queries == [
        TimelineQuery(
            patient_id=1,
            from_=None,
            to=None,
            role=role,
            requested_event_types=None,
            limit=None,
            offset=None,
        )
    ]


def test_requested_types_and_dates_are_normalized_before_service_call() -> None:
    service = StubTimelineService(EMPTY_RESULT)
    client = create_test_client(service)

    with client:
        response = client.get(
            "/api/timeline",
            params={
                "patientId": "1",
                "from": "2024-01-15T12:00:00+02:00",
                "to": "2024-01-15T12:00:00",
                "types": "vitals, imaging,vitals",
            },
            headers={"X-User-Role": "doctor"},
        )

    assert response.status_code == 200
    assert service.received_queries == [
        TimelineQuery(
            patient_id=1,
            from_=START,
            to=datetime(2024, 1, 15, 12, tzinfo=UTC),
            role=UserRole.DOCTOR,
            requested_event_types=(EventType.VITALS, EventType.IMAGING),
            limit=None,
            offset=None,
        )
    ]


@pytest.mark.parametrize("parameter_name", ("from", "to"))
def test_numeric_epoch_date_bound_returns_400(parameter_name: str) -> None:
    service = StubTimelineService(EMPTY_RESULT)
    client = create_test_client(service)

    with client:
        response = client.get(
            "/api/timeline",
            params={"patientId": "1", parameter_name: "1700000000"},
            headers={"X-User-Role": "doctor"},
        )

    assert response.status_code == 400
    assert response.json()["detail"][0]["loc"] == ["query", parameter_name]
    assert service.received_queries == []


@pytest.mark.parametrize(
    ("params", "headers"),
    [
        ({}, {"X-User-Role": "doctor"}),
        ({"patientId": "0"}, {"X-User-Role": "doctor"}),
        ({"patientId": "not-an-integer"}, {"X-User-Role": "doctor"}),
        ({"patientId": "1"}, {}),
        ({"patientId": "1"}, {"X-User-Role": "physician"}),
        ({"patientId": "1", "from": "not-a-date"}, {"X-User-Role": "doctor"}),
        ({"patientId": "1", "to": "not-a-date"}, {"X-User-Role": "doctor"}),
        (
            {
                "patientId": "1",
                "from": "2024-01-16T00:00:00Z",
                "to": "2024-01-15T00:00:00Z",
            },
            {"X-User-Role": "doctor"},
        ),
        (
            {"patientId": "1", "types": "vitals,lab"},
            {"X-User-Role": "doctor"},
        ),
        (
            {"patientId": "1", "types": "vitals,,imaging"},
            {"X-User-Role": "doctor"},
        ),
    ],
)
def test_invalid_request_returns_400(
    params: dict[str, str],
    headers: dict[str, str],
) -> None:
    client = create_test_client(StubTimelineService(EMPTY_RESULT))

    with client:
        response = client.get("/api/timeline", params=params, headers=headers)

    assert response.status_code == 400
    assert "detail" in response.json()


def test_unknown_query_parameter_returns_400() -> None:
    service = StubTimelineService(EMPTY_RESULT)
    client = create_test_client(service)

    with client:
        response = client.get(
            "/api/timeline",
            params={"patientId": "1", "typse": "vitals"},
            headers={"X-User-Role": "doctor"},
        )

    assert response.status_code == 400
    assert "detail" in response.json()
    assert service.received_queries == []


def test_pagination_parameters_reach_service() -> None:
    service = StubTimelineService(EMPTY_RESULT)
    client = create_test_client(service)

    with client:
        response = client.get(
            "/api/timeline",
            params={"patientId": "1", "limit": "2", "offset": "1"},
            headers={"X-User-Role": "doctor"},
        )

    assert response.status_code == 200
    assert service.received_queries == [
        TimelineQuery(
            patient_id=1,
            from_=None,
            to=None,
            role=UserRole.DOCTOR,
            requested_event_types=None,
            limit=2,
            offset=1,
        )
    ]


def test_zero_limit_returns_400() -> None:
    service = StubTimelineService(EMPTY_RESULT)
    client = create_test_client(service)

    with client:
        response = client.get(
            "/api/timeline",
            params={"patientId": "1", "limit": "0"},
            headers={"X-User-Role": "doctor"},
        )

    assert response.status_code == 400
    assert service.received_queries == []


def test_negative_offset_returns_400() -> None:
    service = StubTimelineService(EMPTY_RESULT)
    client = create_test_client(service)

    with client:
        response = client.get(
            "/api/timeline",
            params={"patientId": "1", "offset": "-1"},
            headers={"X-User-Role": "doctor"},
        )

    assert response.status_code == 400
    assert service.received_queries == []


def test_limit_above_max_returns_400() -> None:
    service = StubTimelineService(EMPTY_RESULT)
    client = create_test_client(service)

    with client:
        response = client.get(
            "/api/timeline",
            params={"patientId": "1", "limit": "101"},
            headers={"X-User-Role": "doctor"},
        )

    assert response.status_code == 400
    assert service.received_queries == []


def test_complete_response_uses_frontend_compatible_contract() -> None:
    client = create_test_client(StubTimelineService(COMPLETE_RESULT))

    with client:
        response = client.get(
            "/api/timeline",
            params={"patientId": "1"},
            headers={"X-User-Role": "doctor"},
        )

    assert response.status_code == 200
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
                "children": [
                    {
                        "id": "vitals:vitals:1",
                        "type": "vitals",
                        "source": "vitals",
                        "timestamp": "2024-01-15T10:30:00Z",
                        "patientId": 1,
                        "data": {"bpm": 72, "bp": "120/80"},
                    }
                ],
            }
        ],
        "standalone": [],
        "partial": False,
    }


def test_degraded_response_returns_206_and_deterministic_source_warning() -> None:
    result = TimelineResult(
        parents=COMPLETE_RESULT.parents,
        standalone=(),
        partial=True,
        unavailable_sources=(EventSource.PACS, EventSource.VITALS),
    )
    client = create_test_client(StubTimelineService(result))

    with client:
        response = client.get(
            "/api/timeline",
            params={"patientId": "1"},
            headers={"X-User-Role": "doctor"},
        )

    assert response.status_code == 206
    assert response.json()["partial"] is True
    assert response.json()["warning"] == "Unavailable sources: pacs, vitals"


def test_all_selected_sources_failed_returns_empty_206() -> None:
    result = TimelineResult(
        parents=(),
        standalone=(),
        partial=True,
        unavailable_sources=(
            EventSource.REGISTRY,
            EventSource.PACS,
            EventSource.VITALS,
        ),
    )
    client = create_test_client(StubTimelineService(result))

    with client:
        response = client.get(
            "/api/timeline",
            params={"patientId": "1"},
            headers={"X-User-Role": "doctor"},
        )

    assert response.status_code == 206
    assert response.json() == {
        "parents": [],
        "standalone": [],
        "partial": True,
        "warning": "Unavailable sources: registry, pacs, vitals",
    }


def test_no_selected_sources_returns_empty_200_without_warning() -> None:
    client = create_test_client(StubTimelineService(EMPTY_RESULT))

    with client:
        response = client.get(
            "/api/timeline",
            params={"patientId": "1", "types": "surgery"},
            headers={"X-User-Role": "nurse"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "parents": [],
        "standalone": [],
        "partial": False,
    }


def test_unexpected_error_returns_safe_500_envelope() -> None:
    client = create_test_client(
        FailingTimelineService(RuntimeError("patient 1 dependency body password=private"))
    )

    with client:
        response = client.get(
            "/api/timeline",
            params={"patientId": "1"},
            headers={"X-User-Role": "doctor"},
        )

    assert response.status_code == 500
    assert response.json() == {"detail": "Internal server error"}
    assert "patient 1" not in response.text
    assert "password" not in response.text
