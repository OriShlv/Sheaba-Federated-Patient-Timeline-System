from datetime import UTC, datetime
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from timeline_api.services import TimelineQuery, UserRole, parse_requested_event_types

MAX_PARENT_LIMIT = 100


class TimelineQueryParameters(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    patient_id: int = Field(
        alias="patientId",
        gt=0,
        description="Positive patient identifier.",
        examples=[1],
    )
    from_: datetime | None = Field(
        alias="from",
        default=None,
        description=(
            "Inclusive ISO-8601 lower bound. Timezone-aware values are converted to UTC; "
            "naive values are interpreted as UTC. Numeric epochs are rejected."
        ),
        examples=["2024-01-15T00:00:00Z"],
    )
    to: datetime | None = Field(
        default=None,
        description=(
            "Inclusive ISO-8601 upper bound. Timezone-aware values are converted to UTC; "
            "naive values are interpreted as UTC. Numeric epochs are rejected."
        ),
        examples=["2024-01-16T00:00:00Z"],
    )
    types: str | None = Field(
        default=None,
        description=(
            "Optional comma-separated event types. Allowed values: surgery, "
            "emergency_room, vitals, imaging. Requested types are intersected with the "
            "caller's role permissions and cannot expand access."
        ),
        examples=["vitals,imaging"],
    )
    limit: int | None = Field(
        default=None,
        ge=1,
        le=MAX_PARENT_LIMIT,
        description=(
            "Maximum number of grouped parent events to return. Applied after grouping "
            f"and newest-first parent sorting. Maximum {MAX_PARENT_LIMIT}."
        ),
        examples=[10],
    )
    offset: int | None = Field(
        default=None,
        ge=0,
        description=(
            "Number of grouped parent events to skip. Applied after grouping and "
            "newest-first parent sorting. Standalone events are not paginated."
        ),
        examples=[0],
    )

    @field_validator("from_", "to", mode="before")
    @classmethod
    def validate_iso8601_date_string(cls, value: object) -> object:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("date bounds must be valid ISO-8601 strings")
        try:
            datetime.fromisoformat(value)
        except ValueError:
            raise ValueError("date bounds must be valid ISO-8601 strings") from None
        return value

    @field_validator("types")
    @classmethod
    def normalize_types(cls, value: str | None) -> str | None:
        event_types = parse_requested_event_types(value)
        if event_types is None:
            return None
        return ",".join(event_type.value for event_type in event_types)

    @field_validator("from_", "to")
    @classmethod
    def normalize_dates_to_utc(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_date_order(self) -> Self:
        if self.from_ is not None and self.to is not None and self.from_ > self.to:
            raise ValueError("'from' must be earlier than or equal to 'to'")
        return self


def to_timeline_query(
    parameters: TimelineQueryParameters,
    role: UserRole,
) -> TimelineQuery:
    return TimelineQuery(
        patient_id=parameters.patient_id,
        from_=parameters.from_,
        to=parameters.to,
        role=role,
        requested_event_types=parse_requested_event_types(parameters.types),
        limit=parameters.limit,
        offset=parameters.offset,
    )
