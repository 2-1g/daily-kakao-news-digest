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


def editorial_metrics(*, source_counts: Mapping[str, int], evidence_items: int,
                      total_items: int, domestic_items: int, investment_items: int,
                      cost_usd: Any) -> dict[str, Any]:
    """Produce secret-free operational metrics for Cloud Logging dashboards."""
    total_sources = sum(source_counts.values())
    return {
        "source_concentration": (max(source_counts.values()) / total_sources
                                 if total_sources else 0.0),
        "evidence_coverage": evidence_items / total_items if total_items else 0.0,
        "domestic_ratio": domestic_items / total_items if total_items else 0.0,
        "investment_ratio": investment_items / total_items if total_items else 0.0,
        "estimated_cost_usd": str(cost_usd),
    }
