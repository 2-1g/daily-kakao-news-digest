"""Small structured logger that redacts token-shaped fields."""

import json
import logging
from typing import Any, Mapping


_SECRET_MARKERS = ("token", "secret", "authorization", "credential")


def safe_fields(fields: Mapping[str, Any]) -> dict[str, Any]:
    return {key: "[REDACTED]" if any(marker in key.lower() for marker in _SECRET_MARKERS) else value
            for key, value in fields.items()}


def log_event(logger: logging.Logger, event: str, **fields: Any) -> None:
    logger.info(json.dumps({"event": event, **safe_fields(fields)}, ensure_ascii=False,
                           default=str, sort_keys=True))

