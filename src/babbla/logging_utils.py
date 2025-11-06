"""
Structured logging helpers for Babbla.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping


class LogFormat(str, Enum):
    HUMAN = "human"
    JSON = "json"


def _redact_value(key: str, value: Any) -> Any:
    if not isinstance(value, str):
        return value
    lowered = key.lower()
    if "api_key" in lowered or lowered.endswith("key"):
        if len(value) <= 4:
            return "****"
        return f"****{value[-4:]}"
    return value


class EventLogger:
    """Wrapper that emits structured events in human or JSON format."""

    def __init__(self, logger: logging.Logger, log_format: LogFormat = LogFormat.HUMAN) -> None:
        self.logger = logger
        self.log_format = log_format

    def log(self, event_type: str, *, level: str = "info", **fields: Any) -> None:
        timestamp = datetime.now(timezone.utc).isoformat()
        redacted = {key: _redact_value(key, value) for key, value in fields.items()}
        log_method = getattr(self.logger, level, self.logger.info)

        if self.log_format == LogFormat.JSON:
            payload = {
                "timestamp": timestamp,
                "event": event_type,
                "fields": redacted,
            }
            log_method(json.dumps(payload, separators=(",", ":")))
            return

        field_blob = " ".join(f"{key}={redacted[key]}" for key in sorted(redacted))
        message = f"[{event_type}] {timestamp}"
        if field_blob:
            message = f"{message} | {field_blob}"
        log_method(message)


def create_event_logger(logger: logging.Logger, fmt: str | LogFormat) -> EventLogger:
    try:
        log_format = LogFormat(fmt)
    except ValueError:
        log_format = LogFormat.HUMAN
    return EventLogger(logger, log_format)
