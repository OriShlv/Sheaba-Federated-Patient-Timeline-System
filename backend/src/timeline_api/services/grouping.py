from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from heapq import heappop, heappush

from timeline_api.domain import ChildEvent, ParentEvent

_DATETIME_MIN_UTC = datetime.min.replace(tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class GroupedParent:
    parent: ParentEvent
    children: tuple[ChildEvent, ...]


@dataclass(frozen=True, slots=True)
class GroupingResult:
    parents: tuple[GroupedParent, ...]
    standalone: tuple[ChildEvent, ...]


def _datetime_microseconds(value: datetime) -> int:
    delta = value - _DATETIME_MIN_UTC
    return ((delta.days * 86_400) + delta.seconds) * 1_000_000 + delta.microseconds


def group_events(
    parents: Sequence[ParentEvent],
    children: Sequence[ChildEvent],
) -> GroupingResult:
    """Assign children to active parent intervals without mutating inputs.

    A child belongs to a parent when ``parent.start <= child.timestamp <= parent.end``.
    If several parents overlap, the parent with the latest start wins. Children that
    match no parent are returned as standalone events.
    """
    indexed_parents: list[tuple[int, ParentEvent]] = list(enumerate(parents))
    indexed_parents.sort(key=lambda item: (item[1].start, item[1].id))
    ordered_children: list[ChildEvent] = sorted(
        children,
        key=lambda child: (child.timestamp, child.id),
    )

    children_by_parent: list[list[ChildEvent]] = [[] for _parent in parents]
    standalone: list[ChildEvent] = []
    active_parents: list[tuple[int, str, datetime, int]] = []
    next_parent = 0

    for child in ordered_children:
        while (
            next_parent < len(indexed_parents)
            and indexed_parents[next_parent][1].start <= child.timestamp
        ):
            parent_index, parent = indexed_parents[next_parent]
            heappush(
                active_parents,
                (
                    -_datetime_microseconds(parent.start),
                    parent.id,
                    parent.end,
                    parent_index,
                ),
            )
            next_parent += 1

        while active_parents and active_parents[0][2] < child.timestamp:
            heappop(active_parents)

        if not active_parents:
            standalone.append(child)
            continue

        parent_index = active_parents[0][3]
        children_by_parent[parent_index].append(child)

    ordered_parent_indices = sorted(
        range(len(parents)),
        key=lambda index: (-_datetime_microseconds(parents[index].start), parents[index].id),
    )
    grouped_parents = tuple(
        GroupedParent(
            parent=parents[index],
            children=tuple(children_by_parent[index]),
        )
        for index in ordered_parent_indices
    )
    return GroupingResult(parents=grouped_parents, standalone=tuple(standalone))
