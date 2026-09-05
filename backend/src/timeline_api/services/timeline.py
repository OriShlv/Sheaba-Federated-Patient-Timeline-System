from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from timeline_api.adapters import RegistryAdapter
from timeline_api.domain import ChildEvent, ParentEvent


@dataclass(frozen=True, slots=True)
class TimelineQuery:
    patient_id: int
    from_: datetime | None
    to: datetime | None


@dataclass(frozen=True, slots=True)
class TimelineResult:
    parents: tuple[ParentEvent, ...]
    standalone: tuple[ChildEvent, ...]
    partial: Literal[False]


class TimelineService:
    def __init__(self, registry_adapter: RegistryAdapter) -> None:
        self._registry_adapter = registry_adapter

    async def get_timeline(self, query: TimelineQuery) -> TimelineResult:
        parents = await self._registry_adapter.fetch_parent_events(
            patient_id=query.patient_id,
            from_=query.from_,
            to=query.to,
        )
        return TimelineResult(
            parents=parents,
            standalone=(),
            partial=False,
        )
