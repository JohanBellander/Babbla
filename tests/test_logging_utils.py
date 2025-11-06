from __future__ import annotations

import io
import json
import logging

from babbla.logging_utils import LogFormat, create_event_logger


def _make_logger(name: str):
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    logger.handlers = [handler]
    return logger, handler, stream


def test_json_logging_format():
    logger, handler, stream = _make_logger("babbla.json")
    event_logger = create_event_logger(logger, LogFormat.JSON)
    event_logger.log("chunk_start", index=1, api_key="abcdef1234")
    handler.flush()
    payload = json.loads(stream.getvalue())
    assert payload["event"] == "chunk_start"
    assert payload["fields"]["index"] == 1
    assert payload["fields"]["api_key"].startswith("****")
    logger.handlers.clear()


def test_human_format_contains_event_type():
    logger, handler, stream = _make_logger("babbla.human")
    event_logger = create_event_logger(logger, LogFormat.HUMAN)
    event_logger.log("retry", attempt=2)
    handler.flush()
    message = stream.getvalue()
    assert "[retry]" in message
    assert "attempt=2" in message
    logger.handlers.clear()


def test_redaction_handles_short_keys():
    logger, handler, stream = _make_logger("babbla.redact")
    event_logger = create_event_logger(logger, LogFormat.JSON)
    event_logger.log("auth", api_key="abc")
    handler.flush()
    payload = json.loads(stream.getvalue())
    assert payload["fields"]["api_key"] == "****"
    logger.handlers.clear()
