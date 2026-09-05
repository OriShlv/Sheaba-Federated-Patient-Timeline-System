from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import AfterValidator, AwareDatetime, BaseModel, ConfigDict, Field, model_validator


class EventSource(StrEnum):
    REGISTRY = "registry"
    PACS = "pacs"
    VITALS = "vitals"


class EventType(StrEnum):
    SURGERY = "surgery"
    EMERGENCY_ROOM = "emergency_room"
    IMAGING = "imaging"
    VITALS = "vitals"


def normalize_to_utc(value: datetime) -> datetime:
    return value.astimezone(UTC)


type UtcDateTime = Annotated[AwareDatetime, AfterValidator(normalize_to_utc)]


class DomainModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class SurgeryData(DomainModel):
    surgeon_name: str = Field(min_length=1, serialization_alias="surgeonName")
    procedure: str = Field(min_length=1)


class EmergencyRoomData(DomainModel):
    attending_physician: str = Field(min_length=1, serialization_alias="attendingPhysician")
    chief_complaint: str = Field(min_length=1, serialization_alias="chiefComplaint")


class ImagingData(DomainModel):
    modality: str = Field(min_length=1)
    radiologist_note: str = Field(min_length=1, serialization_alias="radiologistNote")


class VitalsData(DomainModel):
    bpm: int = Field(gt=0)
    bp: str = Field(min_length=1)


class EventModel(DomainModel):
    id: str = Field(min_length=1)
    timestamp: UtcDateTime
    patient_id: int = Field(gt=0, serialization_alias="patientId")


def validate_interval(start: datetime, end: datetime) -> None:
    if end < start:
        raise ValueError("event end must be greater than or equal to event start")


class SurgeryEvent(EventModel):
    type: Literal[EventType.SURGERY]
    source: Literal[EventSource.REGISTRY]
    data: SurgeryData
    start: UtcDateTime
    end: UtcDateTime

    @model_validator(mode="after")
    def validate_dates(self) -> Self:
        validate_interval(self.start, self.end)
        return self


class EmergencyRoomEvent(EventModel):
    type: Literal[EventType.EMERGENCY_ROOM]
    source: Literal[EventSource.REGISTRY]
    data: EmergencyRoomData
    start: UtcDateTime
    end: UtcDateTime

    @model_validator(mode="after")
    def validate_dates(self) -> Self:
        validate_interval(self.start, self.end)
        return self


class ImagingEvent(EventModel):
    type: Literal[EventType.IMAGING]
    source: Literal[EventSource.PACS]
    data: ImagingData


class VitalsEvent(EventModel):
    type: Literal[EventType.VITALS]
    source: Literal[EventSource.VITALS]
    data: VitalsData


type ParentEvent = SurgeryEvent | EmergencyRoomEvent
type ChildEvent = ImagingEvent | VitalsEvent
type TimelineEvent = Annotated[ParentEvent | ChildEvent, Field(discriminator="type")]
