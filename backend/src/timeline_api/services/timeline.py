import asyncio
import logging
from collections.abc import Awaitable
from dataclasses import dataclass
from datetime import datetime
from time import perf_counter
from typing import assert_never

import asyncpg
import httpx
from pymongo.errors import PyMongoError

from timeline_api.adapters import PacsAdapter, RegistryAdapter, VitalsAdapter
from timeline_api.adapters.pacs import PacsDocumentValidationError
from timeline_api.adapters.registry import RegistryRowValidationError
from timeline_api.adapters.vitals import VitalsResponseValidationError
from timeline_api.domain import (
    ChildEvent,
    EmergencyRoomEvent,
    EventSource,
    EventType,
    ImagingEvent,
    ParentEvent,
    SourceOutcome,
    SourceOutcomeStatus,
    SourceSuccess,
    SourceUnavailable,
    SurgeryEvent,
    TimelineEvent,
    VitalsEvent,
)
from timeline_api.logging import OperationalEvent
from timeline_api.services.grouping import GroupedParent, group_events
from timeline_api.services.policy import UserRole, build_access_plan

LOGGER = logging.getLogger(__name__)

type ExpectedSourceErrors = tuple[type[Exception], ...]


@dataclass(frozen=True, slots=True)
class TimelineQuery:
    patient_id: int
    from_: datetime | None
    to: datetime | None
    role: UserRole
    requested_event_types: tuple[EventType, ...] | None
    limit: int | None
    offset: int | None


@dataclass(frozen=True, slots=True)
class TimelineResult:
    parents: tuple[GroupedParent, ...]
    standalone: tuple[ChildEvent, ...]
    partial: bool
    unavailable_sources: tuple[EventSource, ...]


async def _capture_source_outcome(
    source: EventSource,
    operation: Awaitable[tuple[TimelineEvent, ...]],
    expected_errors: ExpectedSourceErrors,
) -> SourceOutcome:
    started_at = perf_counter()
    try:
        events = await operation
    except expected_errors:
        outcome: SourceOutcome = SourceUnavailable(
            status=SourceOutcomeStatus.UNAVAILABLE,
            source=source,
        )
        log_level = logging.WARNING
    else:
        outcome = SourceSuccess(
            status=SourceOutcomeStatus.SUCCESS,
            source=source,
            events=events,
        )
        log_level = logging.INFO

    LOGGER.log(
        log_level,
        "Source fetch completed",
        extra={
            "operational_event": OperationalEvent.SOURCE_FETCH_COMPLETED,
            "source": source.value,
            "outcome": outcome.status.value,
            "duration_ms": round((perf_counter() - started_at) * 1000),
        },
    )
    return outcome


def _authorized_events(
    outcomes: tuple[SourceOutcome, ...],
    effective_event_types: frozenset[EventType],
) -> tuple[TimelineEvent, ...]:
    return tuple(
        event
        for outcome in outcomes
        if isinstance(outcome, SourceSuccess)
        for event in outcome.events
        if event.type in effective_event_types
    )


def _partition_events(
    events: tuple[TimelineEvent, ...],
) -> tuple[tuple[ParentEvent, ...], tuple[ChildEvent, ...]]:
    parents = tuple(
        event for event in events if isinstance(event, (SurgeryEvent, EmergencyRoomEvent))
    )
    children = tuple(event for event in events if isinstance(event, (ImagingEvent, VitalsEvent)))
    return parents, children


def _paginate_parents(
    parents: tuple[GroupedParent, ...],
    limit: int | None,
    offset: int | None,
) -> tuple[GroupedParent, ...]:
    start = 0 if offset is None else offset
    end = None if limit is None else start + limit
    return parents[start:end]


class TimelineService:
    def __init__(
        self,
        registry_adapter: RegistryAdapter,
        pacs_adapter: PacsAdapter,
        vitals_adapter: VitalsAdapter,
    ) -> None:
        self._registry_adapter = registry_adapter
        self._pacs_adapter = pacs_adapter
        self._vitals_adapter = vitals_adapter

    async def get_timeline(self, query: TimelineQuery) -> TimelineResult:
        started_at = perf_counter()
        access_plan = build_access_plan(query.role, query.requested_event_types)
        outcomes = await self._fetch_selected_sources(
            access_plan.required_sources,
            query,
        )
        events = _authorized_events(outcomes, access_plan.effective_event_types)
        parents, children = _partition_events(events)
        grouped = group_events(parents, children)
        unavailable_sources = tuple(
            outcome.source for outcome in outcomes if isinstance(outcome, SourceUnavailable)
        )
        result = TimelineResult(
            parents=_paginate_parents(grouped.parents, query.limit, query.offset),
            standalone=grouped.standalone,
            partial=bool(unavailable_sources),
            unavailable_sources=unavailable_sources,
        )
        LOGGER.info(
            "Timeline request completed",
            extra={
                "operational_event": OperationalEvent.TIMELINE_REQUEST_COMPLETED,
                "selected_sources": tuple(source.value for source in access_plan.required_sources),
                "partial": result.partial,
                "duration_ms": round((perf_counter() - started_at) * 1000),
            },
        )
        return result

    async def _fetch_selected_sources(
        self,
        required_sources: tuple[EventSource, ...],
        query: TimelineQuery,
    ) -> tuple[SourceOutcome, ...]:
        if not required_sources:
            return ()
        return tuple(
            await asyncio.gather(
                *(self._fetch_source(source, query) for source in required_sources)
            )
        )

    async def _fetch_source(
        self,
        source: EventSource,
        query: TimelineQuery,
    ) -> SourceOutcome:
        if source is EventSource.REGISTRY:
            return await _capture_source_outcome(
                source,
                self._registry_adapter.fetch_parent_events(
                    patient_id=query.patient_id,
                    from_=query.from_,
                    to=query.to,
                ),
                (
                    asyncpg.PostgresError,
                    OSError,
                    TimeoutError,
                    RegistryRowValidationError,
                ),
            )
        if source is EventSource.PACS:
            return await _capture_source_outcome(
                source,
                self._pacs_adapter.fetch_imaging_events(
                    patient_id=query.patient_id,
                    from_=query.from_,
                    to=query.to,
                ),
                (PyMongoError, PacsDocumentValidationError),
            )
        if source is EventSource.VITALS:
            return await _capture_source_outcome(
                source,
                self._vitals_adapter.fetch_vitals_events(
                    patient_id=query.patient_id,
                    from_=query.from_,
                    to=query.to,
                ),
                (httpx.HTTPError, VitalsResponseValidationError),
            )
        assert_never(source)
