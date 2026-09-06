import os
from collections import Counter

import pytest
from fastapi.testclient import TestClient

from timeline_api.config import Settings
from timeline_api.main import create_app

LIVE_TESTS_ENABLED = os.getenv("TIMELINE_RUN_LIVE_TESTS") == "1"
pytestmark = pytest.mark.skipif(
    not LIVE_TESTS_ENABLED,
    reason="set TIMELINE_RUN_LIVE_TESTS=1 to test full seeded federation",
)


def timeline_event_type_counts(body: dict[str, object]) -> Counter[str]:
    parents = body["parents"]
    standalone = body["standalone"]
    if not isinstance(parents, list) or not isinstance(standalone, list):
        raise TypeError("timeline response parents and standalone must be lists")

    event_types: list[str] = []
    for parent in parents:
        if not isinstance(parent, dict):
            raise TypeError("timeline parent must be an object")
        parent_type = parent["type"]
        children = parent["children"]
        if not isinstance(parent_type, str) or not isinstance(children, list):
            raise TypeError("timeline parent fields have invalid types")
        event_types.append(parent_type)
        for child in children:
            if not isinstance(child, dict) or not isinstance(child.get("type"), str):
                raise TypeError("timeline child must contain a string type")
            event_types.append(child["type"])

    for event in standalone:
        if not isinstance(event, dict) or not isinstance(event.get("type"), str):
            raise TypeError("standalone event must contain a string type")
        event_types.append(event["type"])

    return Counter(event_types)


def test_live_endpoint_federates_all_sources_and_minimizes_role_and_type_requests() -> None:
    application = create_app(Settings())

    with TestClient(application) as client:
        doctor_response = client.get(
            "/api/timeline",
            params={"patientId": "1"},
            headers={"X-User-Role": "doctor"},
        )
        intern_response = client.get(
            "/api/timeline",
            params={"patientId": "1"},
            headers={"X-User-Role": "intern"},
        )
        vitals_response = client.get(
            "/api/timeline",
            params={"patientId": "1", "types": "vitals"},
            headers={"X-User-Role": "doctor"},
        )

    assert doctor_response.status_code == 200
    assert doctor_response.json()["partial"] is False
    assert timeline_event_type_counts(doctor_response.json()) == {
        "surgery": 3,
        "emergency_room": 2,
        "imaging": 17,
        "vitals": 22,
    }

    assert intern_response.status_code == 200
    assert timeline_event_type_counts(intern_response.json()) == {
        "surgery": 3,
        "emergency_room": 2,
        "vitals": 22,
    }

    assert vitals_response.status_code == 200
    assert timeline_event_type_counts(vitals_response.json()) == {"vitals": 22}
    assert vitals_response.json()["parents"] == []
    assert len(vitals_response.json()["standalone"]) == 22
