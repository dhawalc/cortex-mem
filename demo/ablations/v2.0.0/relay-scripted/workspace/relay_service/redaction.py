"""Recursive payload redaction for the scripted relay."""

from __future__ import annotations

from typing import Any


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if key.endswith("_token") else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value
