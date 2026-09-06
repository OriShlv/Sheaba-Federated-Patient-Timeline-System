from datetime import UTC, datetime, timedelta

import pytest

from timeline_api.domain import (
    ChildEvent,
    EmergencyRoomData,
    EmergencyRoomEvent,
    EventSource,
    EventType,
    ImagingData,
    ImagingEvent,
    ParentEvent,
    SurgeryData,
    SurgeryEvent,
    VitalsData,
    VitalsEvent,
)
from timeline_api.services.grouping import GroupedParent, GroupingResult, group_events

DAY_START = datetime(2024, 1, 15, tzinfo=UTC)


def at(hour: int, minute: int) -> datetime:
    return DAY_START + timedelta(hours=hour, minutes=minute)


def make_surgery(event_id: str, start: datetime, end: datetime) -> SurgeryEvent:
    return SurgeryEvent(
        id=event_id,
        type=EventType.SURGERY,
        source=EventSource.REGISTRY,
        timestamp=start,
        patient_id=1,
        start=start,
        end=end,
        data=SurgeryData(
            surgeon_name="Dr. Williams",
            procedure="Appendectomy",
        ),
    )


def make_emergency_room(
    event_id: str,
    start: datetime,
    end: datetime,
) -> EmergencyRoomEvent:
    return EmergencyRoomEvent(
        id=event_id,
        type=EventType.EMERGENCY_ROOM,
        source=EventSource.REGISTRY,
        timestamp=start,
        patient_id=1,
        start=start,
        end=end,
        data=EmergencyRoomData(
            attending_physician="Dr. Wilson",
            chief_complaint="Chest pain",
        ),
    )


def make_vitals(event_id: str, timestamp: datetime) -> VitalsEvent:
    return VitalsEvent(
        id=event_id,
        type=EventType.VITALS,
        source=EventSource.VITALS,
        timestamp=timestamp,
        patient_id=1,
        data=VitalsData(bpm=72, bp="120/80"),
    )


def make_imaging(event_id: str, timestamp: datetime) -> ImagingEvent:
    return ImagingEvent(
        id=event_id,
        type=EventType.IMAGING,
        source=EventSource.PACS,
        timestamp=timestamp,
        patient_id=1,
        data=ImagingData(
            modality="CT",
            radiologist_note="No abnormalities",
        ),
    )


def find_group(result: GroupingResult, parent_id: str) -> GroupedParent:
    matches = tuple(group for group in result.parents if group.parent.id == parent_id)
    if len(matches) != 1:
        raise AssertionError(f"expected one group for parent {parent_id!r}")
    return matches[0]


def parent_ids(result: GroupingResult) -> list[str]:
    return [group.parent.id for group in result.parents]


def child_ids(group: GroupedParent) -> list[str]:
    return [child.id for child in group.children]


@pytest.mark.parametrize(
    ("child_timestamp", "is_grouped"),
    [
        pytest.param(at(10, 0), True, id="exact-start"),
        pytest.param(at(12, 0), True, id="exact-end"),
        pytest.param(at(9, 59), False, id="immediately-before"),
        pytest.param(at(12, 1), False, id="immediately-after"),
    ],
)
def test_parent_boundaries_are_inclusive_only_inside_interval(
    child_timestamp: datetime,
    is_grouped: bool,
) -> None:
    parent = make_surgery("registry:surgery:1", at(10, 0), at(12, 0))
    child = make_vitals("vitals:vitals:boundary", child_timestamp)

    result = group_events([parent], [child])

    assert child_ids(result.parents[0]) == ([child.id] if is_grouped else [])
    assert [event.id for event in result.standalone] == ([] if is_grouped else [child.id])


def test_one_parent_with_one_child() -> None:
    parent = make_surgery("registry:surgery:1", at(10, 0), at(12, 0))
    child = make_vitals("vitals:vitals:1", at(11, 0))

    result = group_events([parent], [child])

    assert parent_ids(result) == [parent.id]
    assert child_ids(result.parents[0]) == [child.id]
    assert result.standalone == ()


def test_one_parent_with_multiple_children() -> None:
    parent = make_surgery("registry:surgery:1", at(10, 0), at(12, 0))
    children: list[ChildEvent] = [
        make_vitals("vitals:vitals:2", at(11, 30)),
        make_vitals("vitals:vitals:1", at(10, 30)),
    ]

    result = group_events([parent], children)

    assert child_ids(result.parents[0]) == [
        "vitals:vitals:1",
        "vitals:vitals:2",
    ]


def test_parent_without_children_is_returned() -> None:
    parent = make_surgery("registry:surgery:1", at(10, 0), at(12, 0))

    result = group_events([parent], [])

    assert parent_ids(result) == [parent.id]
    assert result.parents[0].children == ()
    assert result.standalone == ()


def test_child_without_parent_is_standalone() -> None:
    child = make_vitals("vitals:vitals:1", at(11, 0))

    result = group_events([], [child])

    assert result.parents == ()
    assert result.standalone == (child,)


def test_latest_start_wins_between_two_overlapping_parents() -> None:
    earlier = make_surgery("registry:surgery:earlier", at(10, 0), at(13, 0))
    later = make_surgery("registry:surgery:later", at(11, 0), at(14, 0))
    child = make_vitals("vitals:vitals:1", at(12, 0))

    result = group_events([earlier, later], [child])

    assert find_group(result, earlier.id).children == ()
    assert child_ids(find_group(result, later.id)) == [child.id]


def test_latest_start_wins_between_three_overlapping_parents() -> None:
    earliest = make_surgery("registry:surgery:earliest", at(9, 0), at(14, 0))
    middle = make_emergency_room("registry:emergency_room:middle", at(10, 0), at(13, 0))
    latest = make_surgery("registry:surgery:latest", at(11, 0), at(12, 0))
    child = make_imaging("pacs:imaging:1", at(11, 30))

    result = group_events([middle, latest, earliest], [child])

    assert find_group(result, earliest.id).children == ()
    assert find_group(result, middle.id).children == ()
    assert child_ids(find_group(result, latest.id)) == [child.id]


def test_child_eligible_only_for_earlier_parent_uses_earlier_parent() -> None:
    earlier = make_surgery("registry:surgery:earlier", at(10, 0), at(14, 0))
    later = make_surgery("registry:surgery:later", at(12, 0), at(13, 0))
    child = make_vitals("vitals:vitals:1", at(11, 0))

    result = group_events([later, earlier], [child])

    assert child_ids(find_group(result, earlier.id)) == [child.id]
    assert find_group(result, later.id).children == ()


def test_expired_later_parent_reveals_still_open_earlier_parent() -> None:
    earlier = make_surgery("registry:surgery:earlier", at(10, 0), at(14, 0))
    later = make_surgery("registry:surgery:later", at(11, 0), at(12, 0))
    during_overlap = make_vitals("vitals:vitals:during", at(11, 30))
    after_later_ends = make_vitals("vitals:vitals:after", at(12, 30))

    result = group_events([earlier, later], [after_later_ends, during_overlap])

    assert child_ids(find_group(result, later.id)) == [during_overlap.id]
    assert child_ids(find_group(result, earlier.id)) == [after_later_ends.id]


def test_equal_parent_starts_use_parent_id_ascending() -> None:
    higher_id = make_surgery("registry:surgery:b", at(10, 0), at(12, 0))
    lower_id = make_surgery("registry:surgery:a", at(10, 0), at(12, 0))
    child = make_vitals("vitals:vitals:1", at(11, 0))

    result = group_events([higher_id, lower_id], [child])

    assert child_ids(find_group(result, lower_id.id)) == [child.id]
    assert find_group(result, higher_id.id).children == ()


def test_result_does_not_depend_on_input_order() -> None:
    lower_id = make_surgery("registry:surgery:a", at(10, 0), at(12, 0))
    higher_id = make_surgery("registry:surgery:b", at(10, 0), at(12, 0))
    first_child = make_vitals("vitals:vitals:a", at(11, 0))
    second_child = make_imaging("pacs:imaging:b", at(11, 0))

    forward = group_events([lower_id, higher_id], [first_child, second_child])
    reversed_inputs = group_events(
        [higher_id, lower_id],
        [second_child, first_child],
    )

    assert forward == reversed_inputs


def test_unmatched_child_becomes_standalone() -> None:
    parent = make_surgery("registry:surgery:1", at(10, 0), at(12, 0))
    child = make_vitals("vitals:vitals:1", at(14, 0))

    result = group_events([parent], [child])

    assert result.parents[0].children == ()
    assert result.standalone == (child,)


def test_multiple_standalone_children_are_chronological() -> None:
    later = make_vitals("vitals:vitals:later", at(14, 0))
    earlier = make_imaging("pacs:imaging:earlier", at(9, 0))

    result = group_events([], [later, earlier])

    assert [child.id for child in result.standalone] == [earlier.id, later.id]


def test_parents_are_newest_first_then_id_ascending() -> None:
    oldest = make_surgery("registry:surgery:oldest", at(8, 0), at(9, 0))
    newest_b = make_surgery("registry:surgery:b", at(10, 0), at(11, 0))
    newest_a = make_emergency_room("registry:emergency_room:a", at(10, 0), at(12, 0))

    result = group_events([oldest, newest_b, newest_a], [])

    assert parent_ids(result) == [newest_a.id, newest_b.id, oldest.id]


def test_children_within_parent_are_chronological() -> None:
    parent = make_surgery("registry:surgery:1", at(10, 0), at(13, 0))
    later = make_vitals("vitals:vitals:later", at(12, 0))
    earlier = make_imaging("pacs:imaging:earlier", at(11, 0))

    result = group_events([parent], [later, earlier])

    assert child_ids(result.parents[0]) == [earlier.id, later.id]


def test_equal_child_timestamps_are_ordered_by_id() -> None:
    parent = make_surgery("registry:surgery:1", at(10, 0), at(12, 0))
    higher_id = make_vitals("vitals:vitals:b", at(11, 0))
    lower_id = make_vitals("vitals:vitals:a", at(11, 0))

    result = group_events([parent], [higher_id, lower_id])

    assert child_ids(result.parents[0]) == [lower_id.id, higher_id.id]


def test_empty_input_returns_empty_result() -> None:
    assert group_events([], []) == GroupingResult(parents=(), standalone=())


def test_only_parents_are_sorted_and_have_empty_children() -> None:
    earlier = make_surgery("registry:surgery:earlier", at(10, 0), at(11, 0))
    later = make_surgery("registry:surgery:later", at(12, 0), at(13, 0))

    result = group_events([earlier, later], [])

    assert parent_ids(result) == [later.id, earlier.id]
    assert all(group.children == () for group in result.parents)


def test_only_children_are_sorted_into_standalone() -> None:
    later = make_vitals("vitals:vitals:later", at(12, 0))
    earlier = make_imaging("pacs:imaging:earlier", at(10, 0))

    result = group_events([], [later, earlier])

    assert result.parents == ()
    assert [child.id for child in result.standalone] == [earlier.id, later.id]


def test_zero_length_parent_accepts_child_at_its_boundary() -> None:
    parent = make_surgery("registry:surgery:zero", at(10, 0), at(10, 0))
    child = make_vitals("vitals:vitals:boundary", at(10, 0))

    result = group_events([parent], [child])

    assert child_ids(result.parents[0]) == [child.id]
    assert result.standalone == ()


def test_multiple_children_exactly_on_parent_boundaries_are_grouped() -> None:
    parent = make_surgery("registry:surgery:1", at(10, 0), at(12, 0))
    at_end = make_vitals("vitals:vitals:end", at(12, 0))
    at_start = make_imaging("pacs:imaging:start", at(10, 0))

    result = group_events([parent], [at_end, at_start])

    assert child_ids(result.parents[0]) == [at_start.id, at_end.id]
    assert result.standalone == ()


def test_grouping_does_not_mutate_input_lists() -> None:
    parent = make_surgery("registry:surgery:1", at(10, 0), at(12, 0))
    child = make_vitals("vitals:vitals:1", at(11, 0))
    parents: list[ParentEvent] = [parent]
    children: list[ChildEvent] = [child]
    parents_before = parents.copy()
    children_before = children.copy()

    group_events(parents, children)

    assert parents == parents_before
    assert children == children_before


def test_grouping_does_not_mutate_or_copy_event_objects() -> None:
    parent = make_surgery("registry:surgery:1", at(10, 0), at(12, 0))
    child = make_vitals("vitals:vitals:1", at(11, 0))
    parent_before = parent.model_dump_json()
    child_before = child.model_dump_json()

    result = group_events([parent], [child])

    assert parent.model_dump_json() == parent_before
    assert child.model_dump_json() == child_before
    assert result.parents[0].parent is parent
    assert result.parents[0].children[0] is child


def test_parent_types_compete_only_by_interval() -> None:
    surgery = make_surgery("registry:surgery:1", at(10, 0), at(13, 0))
    emergency_room = make_emergency_room(
        "registry:emergency_room:1",
        at(11, 0),
        at(12, 0),
    )
    child = make_vitals("vitals:vitals:1", at(11, 30))

    result = group_events([emergency_room, surgery], [child])

    assert child_ids(find_group(result, emergency_room.id)) == [child.id]
    assert find_group(result, surgery.id).children == ()


def test_child_types_group_without_source_specific_logic() -> None:
    parent = make_surgery("registry:surgery:1", at(10, 0), at(12, 0))
    vitals = make_vitals("vitals:vitals:1", at(10, 30))
    imaging = make_imaging("pacs:imaging:1", at(11, 30))

    result = group_events([parent], [imaging, vitals])

    assert child_ids(result.parents[0]) == [vitals.id, imaging.id]
    assert result.standalone == ()
