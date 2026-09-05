from datetime import UTC, datetime
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from timeline_api.services import TimelineQuery


class TimelineQueryParameters(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    patient_id: int = Field(alias="patientId", gt=0)
    from_: datetime | None = Field(alias="from", default=None)
    to: datetime | None = None

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


def to_timeline_query(parameters: TimelineQueryParameters) -> TimelineQuery:
    return TimelineQuery(
        patient_id=parameters.patient_id,
        from_=parameters.from_,
        to=parameters.to,
    )
