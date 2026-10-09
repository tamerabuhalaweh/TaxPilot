"""Structured JSON logging with sensitive-field redaction. No PII/financial payloads in logs."""

import json
import re
from logging import Formatter, LogRecord, StreamHandler, getLogger
from typing import Any

_REDACT_KEYS = {
    "password",
    "token",
    "secret",
    "api_key",
    "apikey",
    "authorization",
    "registration_number",
    "tax_ref",
}
_PATTERN = re.compile(r"(password|token|secret|api[_-]?key|registration_number)\s*[:=]\s*\S+", re.IGNORECASE)


def redact(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: ("***" if k.lower() in _REDACT_KEYS else redact(v)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [redact(v) for v in obj]
    if isinstance(obj, str):
        return _PATTERN.sub(r"\1=***", obj)
    return obj


class JsonFormatter(Formatter):
    def format(self, record: LogRecord) -> str:
        payload = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "correlation_id": getattr(record, "correlation_id", None),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(redact(payload))


def setup_logging(level: str = "INFO") -> None:
    handler = StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())
