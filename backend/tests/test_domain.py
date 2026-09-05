from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from timeline_api.domain import (
    EmergencyRoomData,
    EmergencyRoomEvent,
    EventSource,
    EventType,
    ImagingData,
    ImagingEvent,
    SourceOutcomeStatus,
    SourceSuccess,
    SurgeryData,
    SurgeryEvent,
    VitalsData,
    VitalsEvent,
    build_event_id,
)

UTC_START = datetime(2024, 1, 15, 10, tzinfo=UTC)
UTC_END = datetime(2024, 1, 15, 12, tzinfo=UTC)


def test_all_assignment_event_types_have_typed_normalized_contracts() -> None:
    surgery = SurgeryEvent(
        id="registry:surgery:1",
        type=EventType.SURGERY,
        source=EventSource.REGISTRY,
        timestamp=UTC_START,
        patient_id=1,
        start=UTC_START,
        end=UTC_END,
        data=SurgeryData(surgeon_name="Dr. Williams", procedure="Appendectomy"),
    )
    emergency_room = EmergencyRoomEvent(
        id="registry:emergency_room:1",
        type=EventType.EMERGENCY_ROOM,
        source=EventSource.REGISTRY,
        timestamp=UTC_START,
        patient_id=1,
        start=UTC_START,
        end=UTC_END,
        data=EmergencyRoomData(
            attending_physician="Dr. Wilson",
            chief_complaint="Chest pain",
        ),
    )
    imaging = ImagingEvent(
        id="pacs:imaging:abc",
        type=EventType.IMAGING,
        source=EventSource.PACS,
        timestamp=UTC_START,
        patient_id=1,
        data=ImagingData(modality="CT", radiologist_note="No abnormalities"),
    )
    vitals = VitalsEvent(
        id="vitals:vitals:1:2024-01-15T10:00:00Z",
        type=EventType.VITALS,
        source=EventSource.VITALS,
        timestamp=UTC_START,
        patient_id=1,
        data=VitalsData(bpm=72, bp="120/80"),
    )

    assert [event.type for event in (surgery, emergency_room, imaging, vitals)] == [
        EventType.SURGERY,
        EventType.EMERGENCY_ROOM,
        EventType.IMAGING,
        EventType.VITALS,
    ]
    assert surgery.model_dump(by_alias=True)["patientId"] == 1


def test_event_timestamps_are_normalized_to_utc() -> None:
    timestamp = datetime(2024, 1, 15, 12, tzinfo=timezone(timedelta(hours=2)))
    event = VitalsEvent(
        id="vitals:vitals:1:2024-01-15T10:00:00Z",
        type=EventType.VITALS,
        source=EventSource.VITALS,
        timestamp=timestamp,
        patient_id=1,
        data=VitalsData(bpm=72, bp="120/80"),
    )

    assert event.timestamp == UTC_START


def test_parent_rejects_reversed_interval() -> None:
    with pytest.raises(ValidationError, match="event end must be"):
        SurgeryEvent(
            id="registry:surgery:1",
            type=EventType.SURGERY,
            source=EventSource.REGISTRY,
            timestamp=UTC_START,
            patient_id=1,
            start=UTC_END,
            end=UTC_START,
            data=SurgeryData(surgeon_name="Dr. Williams", procedure="Appendectomy"),
        )


def test_normalized_id_is_stable_and_rejects_empty_source_key() -> None:
    assert build_event_id(EventSource.REGISTRY, EventType.SURGERY, 1) == "registry:surgery:1"

    with pytest.raises(ValueError, match="source_key must not be empty"):
        build_event_id(EventSource.PACS, EventType.IMAGING, " ")


def test_success_outcome_rejects_events_from_another_source() -> None:
    event = ImagingEvent(
        id="pacs:imaging:abc",
        type=EventType.IMAGING,
        source=EventSource.PACS,
        timestamp=UTC_START,
        patient_id=1,
        data=ImagingData(modality="CT", radiologist_note="No abnormalities"),
    )

    with pytest.raises(ValidationError, match="all events must match"):
        SourceSuccess(
            status=SourceOutcomeStatus.SUCCESS,
            source=EventSource.REGISTRY,
            events=(event,),
        )
