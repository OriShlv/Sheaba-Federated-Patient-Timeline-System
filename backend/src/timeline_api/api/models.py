from typing import Annotated, assert_never

from pydantic import Field

from timeline_api.domain import (
    ChildEvent,
    EmergencyRoomEvent,
    EventSource,
    SurgeryEvent,
)
from timeline_api.domain.models import DomainModel
from timeline_api.services import TimelineResult
from timeline_api.services.grouping import GroupedParent


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
    partial: bool
    warning: str | None = None


def to_parent_response(grouped_parent: GroupedParent) -> TimelineParentResponse:
    parent = grouped_parent.parent
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
            children=grouped_parent.children,
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
            children=grouped_parent.children,
        )
    assert_never(parent)


def unavailable_sources_warning(sources: tuple[EventSource, ...]) -> str | None:
    if not sources:
        return None
    return f"Unavailable sources: {', '.join(source.value for source in sources)}"


def to_timeline_response(result: TimelineResult) -> TimelineResponse:
    return TimelineResponse(
        parents=tuple(to_parent_response(parent) for parent in result.parents),
        standalone=result.standalone,
        partial=result.partial,
        warning=unavailable_sources_warning(result.unavailable_sources),
    )
