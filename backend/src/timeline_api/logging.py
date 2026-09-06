import json
import logging
from datetime import UTC, datetime
from enum import StrEnum

from timeline_api.config import LogLevel


class OperationalEvent(StrEnum):
    APPLICATION_STARTED = "application_started"
    APPLICATION_STOPPED = "application_stopped"
    SOURCE_FETCH_COMPLETED = "source_fetch_completed"
    TIMELINE_REQUEST_COMPLETED = "timeline_request_completed"
    TIMELINE_REQUEST_FAILED = "timeline_request_failed"


SAFE_OPERATIONAL_FIELDS = (
    "source",
    "outcome",
    "selected_sources",
    "partial",
    "duration_ms",
)
SENSITIVE_LIBRARY_LOGGERS = ("httpx", "httpcore", "uvicorn.access")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
        }
        operational_event = getattr(record, "operational_event", None)
        if isinstance(operational_event, OperationalEvent):
            entry["event"] = operational_event.value

        for field_name in SAFE_OPERATIONAL_FIELDS:
            value = getattr(record, field_name, None)
            if value is not None:
                entry[field_name] = value

        return json.dumps(entry, separators=(",", ":"), sort_keys=True)


def configure_logging(level: LogLevel) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())

    root_logger = logging.getLogger()
    root_logger.setLevel(level.value)
    root_logger.handlers = [handler]

    for logger_name in SENSITIVE_LIBRARY_LOGGERS:
        logging.getLogger(logger_name).setLevel(logging.WARNING)
