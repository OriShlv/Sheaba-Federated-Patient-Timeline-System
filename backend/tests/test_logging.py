import json
import logging

from timeline_api.config import LogLevel
from timeline_api.logging import JsonFormatter, OperationalEvent, configure_logging


def test_json_formatter_emits_only_allowlisted_operational_context() -> None:
    logger = logging.getLogger("timeline_api.test")
    sensitive_message = "patient_id=1 radiologist_note=private secret=private"
    record = logger.makeRecord(
        name=logger.name,
        level=logging.INFO,
        fn="",
        lno=1,
        msg=sensitive_message,
        args=(),
        exc_info=None,
        extra={
            "operational_event": OperationalEvent.SOURCE_FETCH_COMPLETED,
            "source": "pacs",
            "outcome": "success",
            "duration_ms": 12,
            "patient_id": 1,
            "radiologist_note": "private",
            "raw_error": "private",
            "secret": "private",
        },
    )

    formatted_record = JsonFormatter().format(record)
    entry = json.loads(formatted_record)

    assert entry["event"] == "source_fetch_completed"
    assert entry["source"] == "pacs"
    assert entry["outcome"] == "success"
    assert entry["duration_ms"] == 12
    assert sensitive_message not in formatted_record
    assert "patient_id" not in entry
    assert "radiologist_note" not in entry
    assert "raw_error" not in entry
    assert "secret" not in entry


def test_json_formatter_does_not_emit_unstructured_message_content() -> None:
    logger = logging.getLogger("timeline_api.test")
    sensitive_message = "patient_id=1 bpm=72 secret=private"
    record = logger.makeRecord(
        name=logger.name,
        level=logging.WARNING,
        fn="",
        lno=1,
        msg=sensitive_message,
        args=(),
        exc_info=None,
        extra={"operational_event": sensitive_message},
    )

    formatted_record = JsonFormatter().format(record)
    entry = json.loads(formatted_record)

    assert "event" not in entry
    assert sensitive_message not in formatted_record


def test_logging_suppresses_library_request_urls_at_info() -> None:
    configure_logging(LogLevel.INFO)

    assert not logging.getLogger("httpx").isEnabledFor(logging.INFO)
    assert not logging.getLogger("httpcore").isEnabledFor(logging.INFO)
    assert not logging.getLogger("uvicorn.access").isEnabledFor(logging.INFO)
