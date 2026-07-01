"""Small structured logger that redacts token-shaped fields."""

import json
import logging
import sys
from typing import Any, Mapping


_SECRET_MARKERS = ("token", "secret", "authorization", "credential")


def safe_fields(fields: Mapping[str, Any]) -> dict[str, Any]:
    return {key: "[REDACTED]" if any(marker in key.lower() for marker in _SECRET_MARKERS) else value
            for key, value in fields.items()}


def log_event(logger: logging.Logger, event: str, **fields: Any) -> None:
    logger.info(json.dumps({"event": event, **safe_fields(fields)}, ensure_ascii=False,
                           default=str, sort_keys=True))


def configure_production_logging(logger: logging.Logger) -> logging.Logger:
    """Install exactly one Cloud Run-friendly INFO handler.

    Cloud Run captures stdout/stderr.  The named application logger does not
    inherit a useful level from Python's default WARNING root configuration,
    so INFO structured events otherwise disappear.
    """
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if not any(getattr(handler, "_news_digest_handler", False)
               for handler in logger.handlers):
        # Keep stdout reserved for the command's machine-readable result.
        # Cloud Run captures stderr as structured application log output too.
        handler = logging.StreamHandler(sys.stderr)
        handler.setLevel(logging.INFO)
        handler.setFormatter(logging.Formatter("%(message)s"))
        handler._news_digest_handler = True  # type: ignore[attr-defined]
        logger.addHandler(handler)
    return logger
