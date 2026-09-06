import pytest

from timeline_api.domain import EventSource, EventType
from timeline_api.services.policy import (
    UserRole,
    build_access_plan,
    parse_requested_event_types,
)


@pytest.mark.parametrize(
    ("role", "expected_types"),
    [
        (UserRole.DOCTOR, frozenset(EventType)),
        (
            UserRole.NURSE,
            frozenset(
                {
                    EventType.EMERGENCY_ROOM,
                    EventType.IMAGING,
                    EventType.VITALS,
                }
            ),
        ),
        (
            UserRole.INTERN,
            frozenset(
                {
                    EventType.SURGERY,
                    EventType.EMERGENCY_ROOM,
                    EventType.VITALS,
                }
            ),
        ),
    ],
)
def test_role_allowed_event_types(
    role: UserRole,
    expected_types: frozenset[EventType],
) -> None:
    assert build_access_plan(role, None).effective_event_types == expected_types


def test_requested_types_intersect_with_role_permissions() -> None:
    plan = build_access_plan(
        UserRole.NURSE,
        (EventType.SURGERY, EventType.IMAGING, EventType.VITALS),
    )

    assert plan.effective_event_types == frozenset({EventType.IMAGING, EventType.VITALS})


def test_requested_types_never_expand_permissions() -> None:
    plan = build_access_plan(UserRole.INTERN, (EventType.IMAGING,))

    assert plan.effective_event_types == frozenset()


def test_duplicate_requested_types_keep_first_occurrence() -> None:
    assert parse_requested_event_types("vitals, imaging,vitals") == (
        EventType.VITALS,
        EventType.IMAGING,
    )


@pytest.mark.parametrize("value", ["", ",", "vitals,", ",vitals", "vitals,,imaging"])
def test_malformed_requested_types_are_rejected(value: str) -> None:
    with pytest.raises(ValueError, match="without empty values"):
        parse_requested_event_types(value)


def test_unknown_requested_type_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown event type 'lab'"):
        parse_requested_event_types("vitals,lab")


@pytest.mark.parametrize(
    ("role", "expected_sources"),
    [
        (
            UserRole.DOCTOR,
            (EventSource.REGISTRY, EventSource.PACS, EventSource.VITALS),
        ),
        (
            UserRole.NURSE,
            (EventSource.REGISTRY, EventSource.PACS, EventSource.VITALS),
        ),
        (UserRole.INTERN, (EventSource.REGISTRY, EventSource.VITALS)),
    ],
)
def test_default_source_plan_for_each_role(
    role: UserRole,
    expected_sources: tuple[EventSource, ...],
) -> None:
    assert build_access_plan(role, None).required_sources == expected_sources


def test_vitals_request_selects_only_vitals() -> None:
    plan = build_access_plan(UserRole.DOCTOR, (EventType.VITALS,))

    assert plan.required_sources == (EventSource.VITALS,)


def test_intern_never_selects_pacs() -> None:
    plan = build_access_plan(UserRole.INTERN, None)

    assert EventSource.PACS not in plan.required_sources


def test_no_effective_types_selects_no_sources() -> None:
    plan = build_access_plan(UserRole.NURSE, (EventType.SURGERY,))

    assert plan.required_sources == ()
