from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from timeline_api.domain.models import DomainModel, EventSource, TimelineEvent


class SourceOutcomeStatus(StrEnum):
    SUCCESS = "success"
    UNAVAILABLE = "unavailable"


class SourceSuccess(DomainModel):
    status: Literal[SourceOutcomeStatus.SUCCESS]
    source: EventSource
    events: tuple[TimelineEvent, ...]

    @model_validator(mode="after")
    def validate_event_sources(self) -> Self:
        if any(event.source is not self.source for event in self.events):
            raise ValueError("all events must match the outcome source")
        return self


class SourceUnavailable(DomainModel):
    status: Literal[SourceOutcomeStatus.UNAVAILABLE]
    source: EventSource


type SourceOutcome = Annotated[
    SourceSuccess | SourceUnavailable,
    Field(discriminator="status"),
]
