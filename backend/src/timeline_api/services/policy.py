from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from timeline_api.domain import EventSource, EventType


class UserRole(StrEnum):
    DOCTOR = "doctor"
    NURSE = "nurse"
    INTERN = "intern"


ALL_EVENT_TYPES: frozenset[EventType] = frozenset(EventType)
ROLE_ALLOWED_EVENT_TYPES: Mapping[UserRole, frozenset[EventType]] = {
    UserRole.DOCTOR: ALL_EVENT_TYPES,
    UserRole.NURSE: frozenset(
        {
            EventType.EMERGENCY_ROOM,
            EventType.IMAGING,
            EventType.VITALS,
        }
    ),
    UserRole.INTERN: frozenset(
        {
            EventType.SURGERY,
            EventType.EMERGENCY_ROOM,
            EventType.VITALS,
        }
    ),
}
SOURCE_EVENT_TYPES: tuple[tuple[EventSource, frozenset[EventType]], ...] = (
    (
        EventSource.REGISTRY,
        frozenset({EventType.SURGERY, EventType.EMERGENCY_ROOM}),
    ),
    (EventSource.PACS, frozenset({EventType.IMAGING})),
    (EventSource.VITALS, frozenset({EventType.VITALS})),
)


@dataclass(frozen=True, slots=True)
class AccessPlan:
    effective_event_types: frozenset[EventType]
    required_sources: tuple[EventSource, ...]


def parse_requested_event_types(value: str | None) -> tuple[EventType, ...] | None:
    if value is None:
        return None

    raw_types = value.split(",")
    if any(not raw_type.strip() for raw_type in raw_types):
        raise ValueError("types must be a comma-separated list without empty values")

    event_types: list[EventType] = []
    for raw_type in raw_types:
        normalized_type = raw_type.strip()
        try:
            event_type = EventType(normalized_type)
        except ValueError:
            allowed_values = ", ".join(sorted(item.value for item in EventType))
            raise ValueError(
                f"unknown event type {normalized_type!r}; expected one of: {allowed_values}"
            ) from None
        if event_type not in event_types:
            event_types.append(event_type)

    return tuple(event_types)


def build_access_plan(
    role: UserRole,
    requested_event_types: tuple[EventType, ...] | None,
) -> AccessPlan:
    allowed_event_types = ROLE_ALLOWED_EVENT_TYPES[role]
    effective_event_types = (
        allowed_event_types
        if requested_event_types is None
        else allowed_event_types.intersection(requested_event_types)
    )
    required_sources = tuple(
        source
        for source, source_event_types in SOURCE_EVENT_TYPES
        if effective_event_types.intersection(source_event_types)
    )
    return AccessPlan(
        effective_event_types=effective_event_types,
        required_sources=required_sources,
    )
