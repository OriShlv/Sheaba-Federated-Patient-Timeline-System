from timeline_api.domain.models import EventSource, EventType


def build_event_id(
    source: EventSource,
    event_type: EventType,
    source_key: str | int,
) -> str:
    normalized_key = str(source_key).strip()
    if not normalized_key:
        raise ValueError("source_key must not be empty")

    return f"{source.value}:{event_type.value}:{normalized_key}"
