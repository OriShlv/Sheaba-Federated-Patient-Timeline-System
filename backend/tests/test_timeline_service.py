import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime

import asyncpg
import httpx
import pytest

from timeline_api.adapters import PacsAdapter, RegistryAdapter, VitalsAdapter
from timeline_api.adapters.pacs import PacsDocumentValidationError
from timeline_api.adapters.registry import RegistryRowValidationError
from timeline_api.adapters.vitals import VitalsResponseValidationError
from timeline_api.domain import (
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
from timeline_api.services import TimelineQuery, TimelineResult, TimelineService, UserRole
from timeline_api.services.grouping import GroupedParent

START = datetime(2024, 1, 15, 10, tzinfo=UTC)
END = datetime(2024, 1, 15, 12, tzinfo=UTC)
SURGERY = SurgeryEvent(
    id="registry:surgery:1",
    type=EventType.SURGERY,
    source=EventSource.REGISTRY,
    timestamp=START,
    patient_id=1,
    start=START,
    end=END,
    data=SurgeryData(surgeon_name="Dr. Williams", procedure="Appendectomy"),
)
EMERGENCY_ROOM = EmergencyRoomEvent(
    id="registry:emergency_room:1",
    type=EventType.EMERGENCY_ROOM,
    source=EventSource.REGISTRY,
    timestamp=START,
    patient_id=1,
    start=START,
    end=END,
    data=EmergencyRoomData(
        attending_physician="Dr. Chen",
        chief_complaint="Abdominal pain",
    ),
)
IMAGING = ImagingEvent(
    id="pacs:imaging:1",
    type=EventType.IMAGING,
    source=EventSource.PACS,
    timestamp=datetime(2024, 1, 15, 10, 30, tzinfo=UTC),
    patient_id=1,
    data=ImagingData(modality="CT", radiologist_note="No acute finding"),
)
VITALS = VitalsEvent(
    id="vitals:vitals:1",
    type=EventType.VITALS,
    source=EventSource.VITALS,
    timestamp=datetime(2024, 1, 15, 10, 45, tzinfo=UTC),
    patient_id=1,
    data=VitalsData(bpm=72, bp="120/80"),
)
SOURCE_ORDER: tuple[EventSource, ...] = (
    EventSource.REGISTRY,
    EventSource.PACS,
    EventSource.VITALS,
)
FAILURE_SUBSETS: tuple[frozenset[EventSource], ...] = (
    frozenset({EventSource.REGISTRY}),
    frozenset({EventSource.PACS}),
    frozenset({EventSource.VITALS}),
    frozenset({EventSource.REGISTRY, EventSource.PACS}),
    frozenset({EventSource.REGISTRY, EventSource.VITALS}),
    frozenset({EventSource.PACS, EventSource.VITALS}),
    frozenset(SOURCE_ORDER),
)
FAILURE_SUBSET_IDS: tuple[str, ...] = tuple(
    "-".join(source.value for source in SOURCE_ORDER if source in failed_sources)
    for failed_sources in FAILURE_SUBSETS
)

type FetchHook = Callable[[EventSource], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class AdapterCall:
    patient_id: int
    from_: datetime | None
    to: datetime | None


async def complete_immediately(_source: EventSource) -> None:
    return None


class StubRegistryAdapter(RegistryAdapter):
    def __init__(
        self,
        events: tuple[ParentEvent, ...],
        hook: FetchHook,
    ) -> None:
        self.events = events
        self.hook = hook
        self.calls: list[AdapterCall] = []

    async def fetch_parent_events(
        self,
        patient_id: int,
        from_: datetime | None,
        to: datetime | None,
    ) -> tuple[ParentEvent, ...]:
        self.calls.append(AdapterCall(patient_id, from_, to))
        await self.hook(EventSource.REGISTRY)
        return self.events


class StubPacsAdapter(PacsAdapter):
    def __init__(
        self,
        events: tuple[ImagingEvent, ...],
        hook: FetchHook,
    ) -> None:
        self.events = events
        self.hook = hook
        self.calls: list[AdapterCall] = []

    async def fetch_imaging_events(
        self,
        patient_id: int,
        from_: datetime | None,
        to: datetime | None,
    ) -> tuple[ImagingEvent, ...]:
        self.calls.append(AdapterCall(patient_id, from_, to))
        await self.hook(EventSource.PACS)
        return self.events


class StubVitalsAdapter(VitalsAdapter):
    def __init__(
        self,
        events: tuple[VitalsEvent, ...],
        hook: FetchHook,
    ) -> None:
        self.events = events
        self.hook = hook
        self.calls: list[AdapterCall] = []

    async def fetch_vitals_events(
        self,
        patient_id: int,
        from_: datetime | None,
        to: datetime | None,
    ) -> tuple[VitalsEvent, ...]:
        self.calls.append(AdapterCall(patient_id, from_, to))
        await self.hook(EventSource.VITALS)
        return self.events


class FailingRegistryAdapter(RegistryAdapter):
    def __init__(self, error: Exception) -> None:
        self.error = error
        self.call_count = 0

    async def fetch_parent_events(
        self,
        patient_id: int,
        from_: datetime | None,
        to: datetime | None,
    ) -> tuple[ParentEvent, ...]:
        self.call_count += 1
        raise self.error


class FailingPacsAdapter(PacsAdapter):
    def __init__(self, error: Exception) -> None:
        self.error = error
        self.call_count = 0

    async def fetch_imaging_events(
        self,
        patient_id: int,
        from_: datetime | None,
        to: datetime | None,
    ) -> tuple[ImagingEvent, ...]:
        self.call_count += 1
        raise self.error


class FailingVitalsAdapter(VitalsAdapter):
    def __init__(self, error: Exception) -> None:
        self.error = error
        self.call_count = 0

    async def fetch_vitals_events(
        self,
        patient_id: int,
        from_: datetime | None,
        to: datetime | None,
    ) -> tuple[VitalsEvent, ...]:
        self.call_count += 1
        raise self.error


class ConcurrentCallGate:
    def __init__(self, expected_sources: frozenset[EventSource]) -> None:
        self.expected_sources = expected_sources
        self.started_sources: set[EventSource] = set()
        self.release = asyncio.Event()

    async def wait_for_all_sources(self, source: EventSource) -> None:
        self.started_sources.add(source)
        if self.started_sources == self.expected_sources:
            self.release.set()
        await self.release.wait()


def make_query(
    role: UserRole,
    requested_event_types: tuple[EventType, ...] | None,
) -> TimelineQuery:
    return TimelineQuery(
        patient_id=1,
        from_=None,
        to=None,
        role=role,
        requested_event_types=requested_event_types,
    )


def make_successful_service(
    registry_events: tuple[ParentEvent, ...],
    pacs_events: tuple[ImagingEvent, ...],
    vitals_events: tuple[VitalsEvent, ...],
) -> tuple[TimelineService, StubRegistryAdapter, StubPacsAdapter, StubVitalsAdapter]:
    registry = StubRegistryAdapter(registry_events, complete_immediately)
    pacs = StubPacsAdapter(pacs_events, complete_immediately)
    vitals = StubVitalsAdapter(vitals_events, complete_immediately)
    return TimelineService(registry, pacs, vitals), registry, pacs, vitals


def result_event_ids(result: TimelineResult) -> set[str]:
    return {
        event.id
        for event in (
            *(group.parent for group in result.parents),
            *(child for group in result.parents for child in group.children),
            *result.standalone,
        )
    }


def assert_expected_failure_grouping(
    result: TimelineResult,
    failed_sources: frozenset[EventSource],
) -> None:
    if EventSource.REGISTRY in failed_sources:
        if EventSource.PACS in failed_sources and EventSource.VITALS in failed_sources:
            assert result.parents == ()
            assert result.standalone == ()
        elif EventSource.PACS in failed_sources:
            assert result.parents == ()
            assert result.standalone == (VITALS,)
        elif EventSource.VITALS in failed_sources:
            assert result.parents == ()
            assert result.standalone == (IMAGING,)
        else:
            assert result.parents == ()
            assert result.standalone == (IMAGING, VITALS)
        return

    if EventSource.PACS in failed_sources and EventSource.VITALS in failed_sources:
        assert result.parents == (GroupedParent(parent=SURGERY, children=()),)
        assert result.standalone == ()
        return

    if EventSource.PACS in failed_sources:
        assert result.parents == (GroupedParent(parent=SURGERY, children=(VITALS,)),)
        assert result.standalone == ()
        return

    if EventSource.VITALS in failed_sources:
        assert result.parents == (GroupedParent(parent=SURGERY, children=(IMAGING,)),)
        assert result.standalone == ()
        return


def test_only_selected_sources_are_called() -> None:
    service, registry, pacs, vitals = make_successful_service((), (), (VITALS,))

    result = asyncio.run(service.get_timeline(make_query(UserRole.DOCTOR, (EventType.VITALS,))))

    assert registry.calls == []
    assert pacs.calls == []
    assert len(vitals.calls) == 1
    assert result.standalone == (VITALS,)


def test_independent_selected_sources_execute_concurrently() -> None:
    gate = ConcurrentCallGate(frozenset({EventSource.PACS, EventSource.VITALS}))
    registry = StubRegistryAdapter((), complete_immediately)
    pacs = StubPacsAdapter((IMAGING,), gate.wait_for_all_sources)
    vitals = StubVitalsAdapter((VITALS,), gate.wait_for_all_sources)
    service = TimelineService(registry, pacs, vitals)

    async def run_with_timeout() -> None:
        await asyncio.wait_for(
            service.get_timeline(
                make_query(
                    UserRole.DOCTOR,
                    (EventType.IMAGING, EventType.VITALS),
                )
            ),
            timeout=0.5,
        )

    asyncio.run(run_with_timeout())

    assert gate.started_sources == frozenset({EventSource.PACS, EventSource.VITALS})
    assert registry.calls == []


def test_complete_success_groups_all_authorized_events() -> None:
    service, _registry, _pacs, _vitals = make_successful_service(
        (SURGERY,),
        (IMAGING,),
        (VITALS,),
    )

    result = asyncio.run(service.get_timeline(make_query(UserRole.DOCTOR, None)))

    assert result.partial is False
    assert result.unavailable_sources == ()
    assert len(result.parents) == 1
    assert result.parents[0].parent == SURGERY
    assert result.parents[0].children == (IMAGING, VITALS)
    assert result.standalone == ()


@pytest.mark.parametrize(
    "failed_sources",
    FAILURE_SUBSETS,
    ids=FAILURE_SUBSET_IDS,
)
def test_selected_source_failure_matrix(
    failed_sources: frozenset[EventSource],
) -> None:
    registry: RegistryAdapter = (
        FailingRegistryAdapter(asyncpg.PostgresError("private Registry error"))
        if EventSource.REGISTRY in failed_sources
        else StubRegistryAdapter((SURGERY,), complete_immediately)
    )
    pacs: PacsAdapter = (
        FailingPacsAdapter(PacsDocumentValidationError("private PACS payload"))
        if EventSource.PACS in failed_sources
        else StubPacsAdapter((IMAGING,), complete_immediately)
    )
    vitals: VitalsAdapter = (
        FailingVitalsAdapter(VitalsResponseValidationError("private Vitals payload"))
        if EventSource.VITALS in failed_sources
        else StubVitalsAdapter((VITALS,), complete_immediately)
    )
    service = TimelineService(registry, pacs, vitals)

    result = asyncio.run(service.get_timeline(make_query(UserRole.DOCTOR, None)))

    assert result.partial is True
    assert result.unavailable_sources == tuple(
        source for source in SOURCE_ORDER if source in failed_sources
    )
    assert result_event_ids(result) == {
        event.id
        for source, event in (
            (EventSource.REGISTRY, SURGERY),
            (EventSource.PACS, IMAGING),
            (EventSource.VITALS, VITALS),
        )
        if source not in failed_sources
    }
    assert_expected_failure_grouping(result, failed_sources)


def test_malformed_registry_becomes_degraded_partial_result() -> None:
    service = TimelineService(
        FailingRegistryAdapter(
            RegistryRowValidationError("private malformed row surgeon_name=secret")
        ),
        StubPacsAdapter((IMAGING,), complete_immediately),
        StubVitalsAdapter((VITALS,), complete_immediately),
    )

    result = asyncio.run(service.get_timeline(make_query(UserRole.DOCTOR, None)))

    assert result.partial is True
    assert result.unavailable_sources == (EventSource.REGISTRY,)
    assert result.parents == ()
    assert result.standalone == (IMAGING, VITALS)


def test_unexpected_registry_defect_propagates() -> None:
    service = TimelineService(
        FailingRegistryAdapter(RuntimeError("programming defect")),
        StubPacsAdapter((IMAGING,), complete_immediately),
        StubVitalsAdapter((VITALS,), complete_immediately),
    )

    with pytest.raises(RuntimeError, match="programming defect"):
        asyncio.run(service.get_timeline(make_query(UserRole.DOCTOR, None)))


def test_no_effective_types_make_zero_source_calls() -> None:
    service, registry, pacs, vitals = make_successful_service(
        (SURGERY,),
        (IMAGING,),
        (VITALS,),
    )

    result = asyncio.run(service.get_timeline(make_query(UserRole.NURSE, (EventType.SURGERY,))))

    assert registry.calls == []
    assert pacs.calls == []
    assert vitals.calls == []
    assert result.parents == ()
    assert result.standalone == ()
    assert result.partial is False


def test_expected_transport_failure_becomes_typed_degraded_result() -> None:
    request = httpx.Request("GET", "http://vitals.test/vitals/1")
    service = TimelineService(
        StubRegistryAdapter((), complete_immediately),
        StubPacsAdapter((), complete_immediately),
        FailingVitalsAdapter(httpx.ConnectError("private endpoint", request=request)),
    )

    result = asyncio.run(service.get_timeline(make_query(UserRole.DOCTOR, (EventType.VITALS,))))

    assert result.unavailable_sources == (EventSource.VITALS,)
    assert result.partial is True


def test_unexpected_adapter_defect_propagates() -> None:
    service = TimelineService(
        StubRegistryAdapter((), complete_immediately),
        StubPacsAdapter((), complete_immediately),
        FailingVitalsAdapter(RuntimeError("programming defect")),
    )

    with pytest.raises(RuntimeError, match="programming defect"):
        asyncio.run(service.get_timeline(make_query(UserRole.DOCTOR, (EventType.VITALS,))))


def test_defense_in_depth_filters_disallowed_registry_events() -> None:
    service, registry, pacs, vitals = make_successful_service(
        (SURGERY, EMERGENCY_ROOM),
        (IMAGING,),
        (VITALS,),
    )

    result = asyncio.run(
        service.get_timeline(
            make_query(
                UserRole.NURSE,
                (EventType.SURGERY, EventType.EMERGENCY_ROOM),
            )
        )
    )

    assert len(registry.calls) == 1
    assert tuple(group.parent for group in result.parents) == (EMERGENCY_ROOM,)
    assert result.standalone == ()
    assert pacs.calls == []
    assert vitals.calls == []


def test_authorized_child_becomes_standalone_when_parent_is_filtered_before_grouping() -> None:
    service, _registry, _pacs, _vitals = make_successful_service(
        (SURGERY,),
        (),
        (VITALS,),
    )

    result = asyncio.run(service.get_timeline(make_query(UserRole.NURSE, None)))

    assert result.parents == ()
    assert result.standalone == (VITALS,)


def test_operational_logs_contain_only_safe_failure_metadata(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="timeline_api.services.timeline")
    service = TimelineService(
        StubRegistryAdapter((), complete_immediately),
        FailingPacsAdapter(PacsDocumentValidationError("radiologistNote=private")),
        StubVitalsAdapter((), complete_immediately),
    )

    asyncio.run(service.get_timeline(make_query(UserRole.DOCTOR, None)))

    pacs_record = next(
        record for record in caplog.records if getattr(record, "source", None) == "pacs"
    )
    assert getattr(pacs_record, "outcome", None) == "unavailable"
    assert pacs_record.getMessage() == "Source fetch completed"
    assert "radiologistNote" not in pacs_record.getMessage()
