"""Configuration and fail-closed source compliance registry."""

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Dict, FrozenSet, Iterable, Mapping

from .models import SourceMechanism


class ComplianceError(RuntimeError):
    """Raised before I/O when a source is not demonstrably permitted."""


@dataclass(frozen=True)
class SourcePolicy:
    source_id: str
    owner: str
    mechanism: SourceMechanism
    approved: bool
    permitted_fields: FrozenSet[str]
    attribution_rule: str
    retention_days: int
    terms_url: str
    reviewed_on: date
    expires_on: date

    def assert_usable(self, today: date, requested_fields: Iterable[str]) -> None:
        if not self.approved:
            raise ComplianceError("source is not approved: %s" % self.source_id)
        if today > self.expires_on:
            raise ComplianceError("source approval expired: %s" % self.source_id)
        requested = frozenset(requested_fields)
        disallowed = requested - self.permitted_fields
        if disallowed:
            raise ComplianceError("fields are not permitted: %s" % sorted(disallowed))


class ComplianceRegistry:
    def __init__(self, policies: Mapping[str, SourcePolicy]) -> None:
        self._policies = dict(policies)

    @classmethod
    def from_path(cls, path: Path) -> "ComplianceRegistry":
        payload = json.loads(path.read_text(encoding="utf-8"))
        raw_sources = payload.get("sources")
        if not isinstance(raw_sources, list):
            raise ComplianceError("registry must contain a sources list")
        policies: Dict[str, SourcePolicy] = {}
        for raw in raw_sources:
            policy = _parse_policy(raw)
            if policy.source_id in policies:
                raise ComplianceError("duplicate source id: %s" % policy.source_id)
            policies[policy.source_id] = policy
        return cls(policies)

    def require(self, source_id: str, today: date, fields: Iterable[str]) -> SourcePolicy:
        policy = self._policies.get(source_id)
        if policy is None:
            raise ComplianceError("unknown source: %s" % source_id)
        policy.assert_usable(today, fields)
        return policy


def _required_text(raw: Mapping[str, object], name: str) -> str:
    value = raw.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ComplianceError("missing registry field: %s" % name)
    return value


def _parse_date(raw: Mapping[str, object], name: str) -> date:
    value = _required_text(raw, name)
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ComplianceError("invalid registry date: %s" % name) from exc


def _parse_policy(raw: object) -> SourcePolicy:
    if not isinstance(raw, dict):
        raise ComplianceError("source entry must be an object")
    fields = raw.get("permitted_fields")
    if not isinstance(fields, list) or not fields or not all(isinstance(x, str) for x in fields):
        raise ComplianceError("permitted_fields must be a non-empty string list")
    retention = raw.get("retention_days")
    if not isinstance(retention, int) or retention < 0:
        raise ComplianceError("retention_days must be non-negative")
    approved = raw.get("approved")
    if not isinstance(approved, bool):
        raise ComplianceError("approved must be boolean")
    try:
        mechanism = SourceMechanism(_required_text(raw, "mechanism"))
    except ValueError as exc:
        raise ComplianceError("unsupported source mechanism") from exc
    return SourcePolicy(
        source_id=_required_text(raw, "id"), owner=_required_text(raw, "owner"),
        mechanism=mechanism, approved=approved, permitted_fields=frozenset(fields),
        attribution_rule=_required_text(raw, "attribution_rule"), retention_days=retention,
        terms_url=_required_text(raw, "terms_url"), reviewed_on=_parse_date(raw, "reviewed_on"),
        expires_on=_parse_date(raw, "expires_on"),
    )
