from typing import Annotated, Literal, assert_never

from pydantic import Field

from timeline_api.domain import (
    ChildEvent,
    EmergencyRoomEvent,
    ParentEvent,
    SurgeryEvent,
)
from timeline_api.domain.models import DomainModel
from timeline_api.services import TimelineResult


class SurgeryParentResponse(SurgeryEvent):
    children: tuple[ChildEvent, ...]


class EmergencyRoomParentResponse(EmergencyRoomEvent):
    children: tuple[ChildEvent, ...]


type TimelineParentResponse = Annotated[
    SurgeryParentResponse | EmergencyRoomParentResponse,
    Field(discriminator="type"),
]


class TimelineResponse(DomainModel):
    parents: tuple[TimelineParentResponse, ...]
    standalone: tuple[ChildEvent, ...]
    partial: Literal[False]


def to_parent_response(parent: ParentEvent) -> TimelineParentResponse:
    if isinstance(parent, SurgeryEvent):
        return SurgeryParentResponse(
            id=parent.id,
            type=parent.type,
            source=parent.source,
            timestamp=parent.timestamp,
            patient_id=parent.patient_id,
            data=parent.data,
            start=parent.start,
            end=parent.end,
            children=(),
        )
    if isinstance(parent, EmergencyRoomEvent):
        return EmergencyRoomParentResponse(
            id=parent.id,
            type=parent.type,
            source=parent.source,
            timestamp=parent.timestamp,
            patient_id=parent.patient_id,
            data=parent.data,
            start=parent.start,
            end=parent.end,
            children=(),
        )
    assert_never(parent)


def to_timeline_response(result: TimelineResult) -> TimelineResponse:
    return TimelineResponse(
        parents=tuple(to_parent_response(parent) for parent in result.parents),
        standalone=result.standalone,
        partial=result.partial,
    )
