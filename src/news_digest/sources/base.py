"""HTTP and adapter boundaries with compliance checks before I/O."""

from dataclasses import dataclass
from datetime import date
from typing import Mapping, Protocol, Sequence

from news_digest.config import ComplianceRegistry, SourcePolicy
from news_digest.models import ArticleCandidate


@dataclass(frozen=True)
class HttpResponse:
    status: int
    body: bytes
    headers: Mapping[str, str]


class HttpClient(Protocol):
    def get(self, url: str, headers: Mapping[str, str]) -> HttpResponse:
        ...


class SourceAdapter(Protocol):
    def collect(self, today: date) -> Sequence[ArticleCandidate]:
        ...


class CompliantAdapter:
    source_id: str
    requested_fields: Sequence[str]

    def __init__(self, registry: ComplianceRegistry, http: HttpClient) -> None:
        self.registry = registry
        self.http = http

    def policy(self, today: date) -> SourcePolicy:
        return self.registry.require(self.source_id, today, self.requested_fields)


def require_success(response: HttpResponse) -> bytes:
    if response.status < 200 or response.status >= 300:
        raise RuntimeError("source request failed with status %d" % response.status)
    return response.body

